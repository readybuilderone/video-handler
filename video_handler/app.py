import json
import os
import boto3
from botocore.exceptions import ClientError

import logging
import subprocess

logger = logging.getLogger()
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
s3 = boto3.client('s3')


def lambda_handler(event, context):
    event_type = event.get('detail-type')
    if event_type != 'Object Created':
        logger.warning('Not a supported event type: %s', event_type)
        return

    bucket_name = event['detail']['bucket']['name']
    key = event['detail']['object']['key']

    env_out_bucket = os.environ.get('OutPutBucket', '')
    env_out_path = os.environ.get('OutPutPath', '')
    out_bucket = bucket_name if env_out_bucket == '' else env_out_bucket
    out_path = "video-handler-output" if env_out_path == '' else env_out_path
    return extract_frame(bucket_name, key, out_bucket, out_path)


def video_api_handler(event, context):
    logger.info('event: %s', event)
    data: dict = json.loads(event['body'])
    
    # 验证input参数包含必填项 bucketName, key
    if not 'bucketName' in data:
        return {
            "statusCode": 400,
            "body": json.dumps({"bad request": "bucketName is required"})
        }
    if not 'key' in data:
        return {
            "statusCode": 400,
            "body": json.dumps({"bad request": "key is required"})
        }
    
    bucket_name = data['bucketName']
    key = data['key']
    time_off = data.get('timeOff')
    time_off = time_off if time_off else '00:00:00'
    # 验证要被处理的视频存在
    if not check_file_existence(bucket_name, key):
        logger.error('s3://%s/%s not existed', bucket_name, key)
        return {
            "statusCode": 400,
            "body": json.dumps({"bad request": "file not existed",
                                "bucket_name": bucket_name,
                                "file": key})
        }
        
    out_bucket = bucket_name if not 'outBucketName' in data else data['outBucketName']
    out_path = "video-handler-output" if not 'outPath' in data else data['outPath']
    logger.info('out_bucket_name: %s, out_path: %s', out_bucket, out_path) 

    result = extract_frame(bucket_name, key, out_bucket, out_path, time_off)
    logger.info('result a: %s', result)
    result['requestId'] = data.get('requestId')
    return {
        "statusCode": 200,
        "body": json.dumps(result)
    }


def check_file_existence(bucket_name, file_key):
    try:
        s3.head_object(Bucket=bucket_name, Key=file_key)
        return True
    except ClientError as e:
        return False


def extract_frame(bucket_name, key, out_bucket, out_path, time_off='00:00:00'):
    output_key = f"{out_path}/{os.path.basename(key)}.jpg"
    presigned_url = generate_presigned_url(bucket_name, key)

    # 调用 FFprobe 获取视频时长
    ffprobe_command = f"ffprobe -v error -select_streams v:0 -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {presigned_url}"
    process = subprocess.Popen(ffprobe_command.split(), stdout=subprocess.PIPE)
    output, _ = process.communicate()

    # 获取视频时长（以秒为单位）
    duration = float(output)
    logger.info(f"Video duration: {duration} seconds")

    # 调用FFmpeg提取第一帧图像
    ffmpeg_command = f"/opt/bin/ffmpeg -loglevel quiet -i {presigned_url} -ss {time_off} -vframes 1 -f image2 -c:v mjpeg -"
    logger.info("Executed ffmpeg command: %s", ffmpeg_command)
    process = subprocess.Popen(ffmpeg_command.split(), stdout=subprocess.PIPE)
    frame_data, _ = process.communicate()

    # 将图像上传到S3
    s3.put_object(Body=frame_data, Bucket=out_bucket, Key=output_key, Metadata={'duration': f"{duration}"},
                  ContentType='image/jpeg')

    logger.info(f"Frame image saved to: s3://{out_bucket}/{output_key}")

    return {
        "originVideo": f"s3://{bucket_name}/{key}",
        "image": f"s3://{out_bucket}/{output_key}",
        "duration": duration
    }


def generate_presigned_url(bucket_name, key, expiration=3600):
    response = s3.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': bucket_name,
            'Key': key
        },
        ExpiresIn=expiration
    )
    return response
