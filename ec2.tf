provider "aws" {
  region  = var.aws_region
  profile = var.profile
}

# IAM role for EC2 instances
resource "aws_iam_role" "pointcloud_ec2_role" {
  name = "pointcloud_ec2_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# IAM role policy attachment for CloudWatch
resource "aws_iam_role_policy_attachment" "cloudwatch_agent_policy" {
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
  role       = aws_iam_role.pointcloud_ec2_role.name
}

# IAM role policy attachment for api.py
resource "aws_iam_role_policy_attachment" "s3_access_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
  role       = aws_iam_role.pointcloud_ec2_role.name
}

# IAM role policy attachment for SSM
resource "aws_iam_role_policy_attachment" "ec2_ssm_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  role       = aws_iam_role.pointcloud_ec2_role.name
}

# IAM instance profile
resource "aws_iam_instance_profile" "pointcloud_ec2_profile" {
  name = "pointcloud_ec2_profile"
  role = aws_iam_role.pointcloud_ec2_role.name
}

# Security group for EC2 instances
resource "aws_security_group" "ec2_sg" {
  name        = "ec2_sg"
  description = "Security group for EC2 instances"
}

resource "aws_security_group_rule" "ingress_api" {
  type              = "ingress"
  from_port         = 5000
  to_port           = 5000
  protocol          = "tcp"
  cidr_blocks       = var.ingress_cidr_blocks
  security_group_id = aws_security_group.ec2_sg.id
}

resource "aws_security_group_rule" "ingress_rdp" {
  type              = "ingress"
  from_port         = 3389
  to_port           = 3389
  protocol          = "tcp"
  cidr_blocks       = var.ingress_cidr_blocks
  security_group_id = aws_security_group.ec2_sg.id
}

resource "aws_security_group_rule" "egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ec2_sg.id
}

# S3 Bucket
resource "aws_s3_bucket" "image_processing_bucket" {
  bucket = var.s3_bucket_name
}

# Upload api.py to S3
resource "aws_s3_object" "api_py" {
  depends_on = [aws_s3_bucket.image_processing_bucket]
  bucket     = var.s3_bucket_name
  key        = var.s3_key
  source     = "./ec2/api.py"
}

# Launch template
resource "aws_launch_template" "api_server" {
  name          = "api_server_template"
  image_id      = var.custom_ami_id
  instance_type = var.instance_type
  key_name      = var.ec2_key_name
  depends_on    = [aws_s3_object.api_py, aws_iam_instance_profile.pointcloud_ec2_profile]

  network_interfaces {
    associate_public_ip_address = true
    subnet_id                   = var.subnet_ids[0]
    security_groups             = [aws_security_group.ec2_sg.id]
  }

  iam_instance_profile {
    name = aws_iam_instance_profile.pointcloud_ec2_profile.name
  }

  # block_device_mappings {
  #   device_name = "/dev/sda1"
  #   ebs {
  #     snapshot_id = var.custome_snap_id
  #     # volume_size = 60
  #     delete_on_termination = true
  #     # volume_type = "gp2"
  #   }
  # }

  user_data = base64encode(<<-EOF
              <powershell>
              Start-Transcript -Path C:\userdata_execution.log

              try {

                  # Download api.py from S3
                  $s3bucket = "${var.s3_bucket_name}"
                  $s3key = "${var.s3_key}"
                  Read-S3Object -BucketName $s3bucket -Key $s3key -File C:\MeditAutoTest\api.py
                  
                  # Allow 5000 port
                  New-NetFirewallRule -DisplayName "Allow Port 5000" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow

                  # Simple Start the API server
                  Start-Process python -ArgumentList "C:\MeditAutoTest\api.py" -WorkingDirectory "C:\MeditAutoTest\9999.0.0.4514_Release"

                  Write-Host "User data script execution completed successfully."
              }
              catch {
                  Write-Host "An error occurred during user data script execution: $_"
                  $_ | Out-File -FilePath C:\userdata_error.log
              }
              finally {
                  Stop-Transcript
              }
              </powershell>
              <persist>true</persist>
              EOF
  )
}

# Create an EC2 instance using Launch Template
resource "aws_instance" "pointcloud_server" {
  launch_template {
    id      = aws_launch_template.api_server.id
    version = "$Latest"
  }

  tags = {
    Name = "pointcloud_server"
  }
}

