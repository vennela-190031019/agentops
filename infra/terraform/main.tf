locals {
  name = "${var.project_name}-${var.environment}"
}

# ---------------------------------------------------------------------------
# ECR
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ---------------------------------------------------------------------------
# CloudWatch logs
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}-api"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# Secret: AGENTOPS_API_KEYS as a SecureString SSM parameter, injected into
# the task via the container definition's `secrets` block -- never as a
# plain environment variable baked into the task definition.
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "api_keys" {
  name  = "/${local.name}/AGENTOPS_API_KEYS"
  type  = "SecureString"
  value = var.agentops_api_keys
}

# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: pulls the image from ECR, ships logs to CloudWatch, and
# reads the AGENTOPS_API_KEYS parameter on the task's behalf at launch.
resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_ssm" {
  statement {
    actions   = ["ssm:GetParameters"]
    resources = [aws_ssm_parameter.api_keys.arn]
  }
}

resource "aws_iam_role_policy" "execution_ssm" {
  name   = "${local.name}-execution-ssm"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_ssm.json
}

# Task role: the app's own AWS identity at runtime. The API doesn't call any
# AWS APIs today, so it starts empty -- attach permissions here if that
# changes, rather than widening the execution role above.
resource "aws_iam_role" "task" {
  name               = "${local.name}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Internet-facing ALB for the AgentOps API"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name        = "${local.name}-service"
  description = "AgentOps API Fargate tasks -- only reachable from the ALB"
  vpc_id      = var.vpc_id

  ingress {
    description     = "API port from the ALB only"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------
# ALB
# ---------------------------------------------------------------------------

resource "aws_lb" "api" {
  name               = "${local.name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.health_check_path
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }
}

# Plain HTTP listener only -- no ACM cert/domain is assumed here. Add an
# aws_lb_listener on 443 with an aws_acm_certificate once a domain exists.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ---------------------------------------------------------------------------
# ECS (Fargate)
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = local.name
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential = true
      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "AGENTOPS_DB_PATH", value = "/app/data/agentops.db" },
        { name = "AGENTOPS_CHECKPOINT_DB", value = "/app/data/agentops_checkpoints.db" },
      ]
      secrets = [
        { name = "AGENTOPS_API_KEYS", valueFrom = aws_ssm_parameter.api_keys.arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

# NOTE (honest limitation): Fargate's container filesystem is ephemeral, so
# the SQLite trace/approval/checkpoint data does NOT persist across task
# replacement the way the docker-compose named volume does locally. A real
# deployment would move this to EFS (via an aws_efs_file_system +
# efs_volume_configuration on the task definition) or, better, swap SQLite
# for a managed DB -- both are out of scope for this "validate only" pass.
resource "aws_ecs_service" "api" {
  name            = "${local.name}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]
}
