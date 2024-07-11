from flask import Flask, request, jsonify
import json
import boto3
import os
import subprocess
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import threading
from botocore.exceptions import ClientError
import urllib.request
import json
import shutil

app = Flask(__name__)

# Configuration for CloudWatch Client
cloudwatch_logs = boto3.client('logs')
log_group_name = '/medit-auto-test/api-logs'
log_stream_name = f'api-log-stream-{int(time.time())}'

try:
    cloudwatch_logs.create_log_group(logGroupName=log_group_name)
except cloudwatch_logs.exceptions.ResourceAlreadyExistsException:
    pass

try:
    cloudwatch_logs.create_log_stream(logGroupName=log_group_name, logStreamName=log_stream_name)
except cloudwatch_logs.exceptions.ResourceAlreadyExistsException:
    pass

class CloudWatchLogsHandler(logging.Handler):
    def __init__(self, log_group_name, log_stream_name):
        super().__init__()
        self.log_group_name = log_group_name
        self.log_stream_name = log_stream_name
        self.sequence_token = None

    def emit(self, record):
        log_entry = self.format(record)
        timestamp = int(record.created * 1000)  # CloudWatch expects timestamp in milliseconds

        try:
            kwargs = {
                'logGroupName': self.log_group_name,
                'logStreamName': self.log_stream_name,
                'logEvents': [
                    {
                        'timestamp': timestamp,
                        'message': log_entry
                    }
                ]
            }
            if self.sequence_token:
                kwargs['sequenceToken'] = self.sequence_token

            response = cloudwatch_logs.put_log_events(**kwargs)
            self.sequence_token = response['nextSequenceToken']
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidSequenceTokenException':
                self.sequence_token = e.response['Error']['Message'].split()[-1]
                self.emit(record)  # Retry with the correct sequence token
            else:
                print(f"Failed to send logs to CloudWatch: {e}", file=sys.stderr)

# Configuration for logging
logger = logging.getLogger("ImageProcessing")
logger.setLevel(logging.INFO)

# File Handler for logger (Optional for local debugging)
#log_dir = "C:\\MeditAutoTest\\logs"
#os.makedirs(log_dir, exist_ok=True)
#log_file = os.path.join(log_dir, "image_processing.log")
#file_handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7)
#file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
#file_handler.setFormatter(file_formatter)
#logger.addHandler(file_handler)

# CloudWatch Handler for logger
cloudwatch_handler = CloudWatchLogsHandler(log_group_name, log_stream_name)
cloudwatch_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
cloudwatch_handler.setFormatter(cloudwatch_formatter)
logger.addHandler(cloudwatch_handler)

# Very simple dictionary for job status and time
job_status = {}
job_start_times = {}

# Get Region from EC2 instance's metadata
def get_instance_region():
    try:
        with urllib.request.urlopen("http://169.254.169.254/latest/meta-data/placement/region", timeout=1) as response:
            return response.read().decode('utf-8')
    except urllib.error.URLError:
        logger.error("Failed to retrieve instance region from metadata")
        return None

# Get temporary credentials from EC2 instance metadata
def get_instance_credentials():
    try:
        with urllib.request.urlopen("http://169.254.169.254/latest/meta-data/iam/security-credentials/", timeout=1) as response:
            role_name = response.read().decode('utf-8')
        
        with urllib.request.urlopen(f"http://169.254.169.254/latest/meta-data/iam/security-credentials/{role_name}", timeout=1) as response:
            credentials = json.loads(response.read().decode('utf-8'))
        return credentials
    except urllib.error.URLError:
        logger.error("Failed to retrieve instance credentials from metadata")
        return None

# Create boto3 session using region information and temporary credentials
def create_boto3_session():
    region = get_instance_region()
    credentials = get_instance_credentials()
    
    if region and credentials:
        session = boto3.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['Token'],
            region_name=region
        )
        return session
    else:
        logger.error("Failed to create boto3 session")
        return None

# boto3 session
session = create_boto3_session()

if session:
    s3 = session.client("s3")
    cloudwatch = session.client('cloudwatch')
else:
    logger.error("Failed to initialize AWS clients")
    s3 = None
    cloudwatch = None

def download_from_s3(s3_uri, local_path):
    if not s3:
        logger.error("S3 client is not initialized")
        return
    
    try:
        bucket_name = s3_uri.split("/")[2]
        prefix = "/".join(s3_uri.split("/")[3:])
        
        logger.info(f"Attempting to download from bucket: {bucket_name}, prefix: {prefix}")
        
        # 버킷 내 객체 리스트 확인 및 다운로드
        paginator = s3.get_paginator('list_objects_v2')
        count = 0
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            if 'Contents' in page:
                for obj in page['Contents']:
                    count += 1
                    file_key = obj['Key']
                    if file_key.endswith('/'):  # S3 콘솔에서 생성된 '폴더'는 끝에 /가 있는 객체입니다
                        continue
                    
                    # 로컬 파일 경로 생성
                    relative_path = os.path.relpath(file_key, prefix)
                    local_file_path = os.path.join(local_path, relative_path)
                    
                    # 필요한 디렉토리 생성
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    
                    # 파일 다운로드
                    logger.info(f"Downloading {file_key} to {local_file_path}")
                    s3.download_file(bucket_name, file_key, local_file_path)

        if count == 0:
            logger.warning(f"No objects found with the given prefix: {prefix}")
        else:
            logger.info(f"Successfully downloaded {count} objects from {s3_uri} to {local_path}")
    
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            logger.error(f"The bucket does not exist. Bucket: {bucket_name}")
        else:
            logger.error(f"Error downloading from S3: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error downloading from S3: {str(e)}")


def upload_to_s3(local_path, s3_uri):
    if not s3:
        logger.error("S3 client is not initialized")
        return
    
    try:
        bucket_name = s3_uri.split("/")[2]
        prefix = "/".join(s3_uri.split("/")[3:])
        
        logger.info(f"Attempting to upload from {local_path} to bucket: {bucket_name}, prefix: {prefix}")
        
        upload_count = 0
        for root, dirs, files in os.walk(local_path):
            for file in files:
                local_file_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_file_path, local_path)
                s3_key = os.path.join(prefix, relative_path).replace("\\", "/")
                
                logger.info(f"Uploading {local_file_path} to s3://{bucket_name}/{s3_key}")
                s3.upload_file(local_file_path, bucket_name, s3_key)
                upload_count += 1
        
        logger.info(f"Successfully uploaded {upload_count} files from {local_path} to {s3_uri}")
    
    except ClientError as e:
        logger.error(f"Error uploading to S3: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error uploading to S3: {str(e)}")

def process_images(job_id, config):
    try:
        logger.info(f"Starting image processing task for job {job_id}")
        job_status[job_id] = "processing"
        job_start_times[job_id] = time.time()

        source_s3_uri = config["Source Folder Path"]
        target_s3_uri = config["Target Folder Path"]

        local_source_path = f"C:\\MeditAutoTest\\src_{job_id}"
        download_from_s3(source_s3_uri, local_source_path)

        local_target_path = f"C:\\MeditAutoTest\\target_{job_id}"
        config["Source Folder Path"] = local_source_path
        config["Target Folder Path"] = local_target_path

        config_path = os.path.join(local_source_path, "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)

        start_time = time.time()

        logger.info(f"Current working directory: {os.getcwd()}")

        args = r'--iScanComplete \"{config_path}\"'
        logger.info(f"Attempting to run command with args: {args}")
        
        process = subprocess.Popen(
            ["Medit_AutoTest.exe", "--iScanComplete", config_path], 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            )

        for line in process.stdout:
            logger.info(line.decode().strip())
        for line in process.stderr:
            logger.error(line.decode().strip())

        process.wait()
        end_time = time.time()

        upload_to_s3(f"C:\\MeditAutoTest\\target_{job_id}", target_s3_uri)

        duration = end_time - start_time
        logger.info(f"Image processing completed in {duration:.2f} seconds for job {job_id}")
        
        if cloudwatch:
            cloudwatch.put_metric_data(
                Namespace='CustomMetrics',
                MetricData=[
                    {
                        'MetricName': 'ProcessingDuration',
                        'Value': duration,
                        'Unit': 'Seconds'
                    },
                ]
            )
        else:
            logger.error("CloudWatch client is not initialized, cannot put metric data")

        job_status[job_id] = "completed"
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        job_status[job_id] = "failed"
    finally:
        job_start_times.pop(job_id, None)
        try:
            shutil.rmtree(local_source_path)
            shutil.rmtree(local_target_path)
            logger.info(f"Cleaned up temporary directories for job {job_id}")
        except Exception as e:
            logger.error(f"Error cleaning up temporary directories: {str(e)}")
        

@app.route('/process', methods=['POST'])
def start_processing():
    config = request.json
    job_id = str(int(time.time()))  # Very simple Unique job ID
    threading.Thread(target=process_images, args=(job_id, config)).start()
    return jsonify({"job_id": job_id, "status": "started"}), 202

# For getting status of specific job
@app.route('/job/<job_id>', methods=['GET'])
def get_job_status(job_id):
    status = job_status.get(job_id, "not_found")
    return jsonify({"job_id": job_id, "status": status})

# For getting status of all jobs
@app.route('/jobs', methods=['GET'])
def get_all_job_status():
    current_time = time.time()
    job_list = []
    for job_id, status in job_status.items():
        job_info = {
            "job_id": job_id,
            "status": status,
        }
        if status == "processing":
            start_time = job_start_times.get(job_id)
            if start_time:
                duration = current_time - start_time
                job_info["duration"] = f"{duration:.2f} seconds"
        job_list.append(job_info)
    
    return jsonify({"jobs": job_list}), 200

# For AWS EC2 Health Check
@app.route('/status/health', methods=['GET'])
def get_health_status():
    return jsonify({"status": "ready"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
