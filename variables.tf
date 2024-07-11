variable "aws_region" {
  description = "The AWS region to deploy to"
  default     = "ap-northeast-2"
}

variable "profile" {
  description = "The AWS profile to use"
  default     = "dev"
}

variable "custom_ami_id" {
  description = "The name of the custom AMI to use"
  type        = string
  default     = "ami-0b974a2f26d4dad47"
}

variable "custome_snap_id" {
  description = "The name of the custom snapshot to use"
  type        = string
  default     = "snap-0ede3736964b134b9"
  
}

variable "ec2_key_name" {
  description = "The name of the EC2 key pair to use"
  type        = string
  default     = "point-cloud-test"
}

variable "s3_bucket_name" {
  description = "The name of the S3 bucket for api.py"
  type        = string
  default     = "pointcloud-api-bucket"
}

variable "s3_key" {
  description = "The key of the S3 object for api.py"
  type        = string
  default     = "api.py"
}

variable "instance_type" {
  description = "The instance type to use for EC2 instances"
  default     = "g4dn.xlarge"
}

variable "desired_capacity" {
  description = "The desired number of EC2 instances in the ASG"
  default     = 1
}

variable "max_size" {
  description = "The maximum number of EC2 instances in the ASG"
  default     = 3
}

variable "min_size" {
  description = "The minimum number of EC2 instances in the ASG"
  default     = 1
}

variable "subnet_ids" {
  description = "The subnet IDs to deploy the EC2 instances into"
  type        = list(string)
  default     = ["subnet-004f4d83cf888e96d", "subnet-09fcd95b4cbf24f13"]
}

variable "vpc_id" {
  description = "The ID of the VPC to deploy into"
  type        = string
  default     = "vpc-585abb33"
}

variable "ingress_cidr_blocks" {
  description = "The CIDR blocks to allow ingress traffic from"
  type        = list(string)
  default     = ["1.223.27.37/32"]
}

variable "processing_time_threshold" {
  description = "The threshold for processing time to trigger scaling (in seconds)"
  default     = 600
}
