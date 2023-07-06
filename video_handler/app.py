import json
import os
import boto3

import logging
import shlex
import subprocess

# import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
s3 = boto3.client('s3')

def lambda_handler(event, context):
    logger.info('This is an info message')
    logger.warning('This is a warning message')
    logger.error('This is an error message')    
    
    logger.info('event: %s', event)
    
    event_type = event.get('detail-type')
    if event_type != 'Object Created':
        logger.warning('Not a supported event type: %s', event_type)
        return
    
    bucket_name =  event['detail']['bucket']['name']
    key = event['detail']['object']['key']
    
    output_key = f"video-handler-output/{os.path.basename(key)}.jpg"
    
    presigned_url = generate_presigned_url(bucket_name, key)
    
    # 调用 FFprobe 获取视频时长
    ffprobe_command = f"ffprobe -v error -select_streams v:0 -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {presigned_url}"
    process = subprocess.Popen(ffprobe_command.split(), stdout=subprocess.PIPE)
    output, _ = process.communicate()
        
    # 获取视频时长（以秒为单位）
    duration = float(output)
        
    logger.info(f"Video duration: {duration} seconds")
        
    # 调用FFmpeg提取第一帧图像
    
    ffmpeg_command = f"/opt/bin/ffmpeg -loglevel quiet  -i {presigned_url} -vframes 1 -f image2 -c:v mjpeg -"
    process = subprocess.Popen(ffmpeg_command.split(), stdout=subprocess.PIPE)
    first_frame_data, _ = process.communicate()
        
    # 将图像上传到S3
    s3.put_object(Body=first_frame_data, Bucket=bucket_name, Key=output_key, Metadata={'duration': f"{duration}"})
        
    logger.info(f"First frame image saved to: s3://{bucket_name}/{output_key}")
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "image": f"s3://{bucket_name}/{output_key}"
        }),
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
