variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used to prefix all resources (ECR repo, log group, ECS cluster, etc.)."
  type        = string
  default     = "agentops"
}

variable "environment" {
  description = "Deployment environment name, e.g. dev/staging/prod."
  type        = string
  default     = "dev"
}

variable "vpc_id" {
  description = "VPC the ALB, security groups and Fargate tasks live in."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for the Application Load Balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the Fargate service's ENIs."
  type        = list(string)
}

variable "container_port" {
  description = "Port the API container listens on (matches the Dockerfile's EXPOSE / uvicorn --port)."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "Path the ALB target group health-checks (the API's open, unauthenticated health endpoint)."
  type        = string
  default     = "/health"
}

variable "task_cpu" {
  description = "Fargate task CPU units (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Number of API task instances to run."
  type        = number
  default     = 1
}

variable "image_tag" {
  description = "Tag of the image in ECR to deploy (pushed out-of-band by CI/CD, not by this Terraform)."
  type        = string
  default     = "latest"
}

variable "log_retention_days" {
  description = "CloudWatch log group retention."
  type        = number
  default     = 14
}

variable "agentops_api_keys" {
  description = "JSON {key: role} map for AGENTOPS_API_KEYS, stored as a SecureString SSM parameter and injected into the task as a secret (never a plain container env var). Supply via TF_VAR_agentops_api_keys or a tfvars file that is never committed."
  type        = string
  sensitive   = true
  default     = ""
}
