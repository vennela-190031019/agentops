output "ecr_repository_url" {
  description = "Push images here (e.g. docker push <url>:<tag>) before the ECS service can pull a new version."
  value       = aws_ecr_repository.api.repository_url
}

output "alb_dns_name" {
  description = "Public DNS name of the ALB in front of the API."
  value       = aws_lb.api.dns_name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.api.name
}
