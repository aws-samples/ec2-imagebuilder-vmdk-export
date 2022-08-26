#!/usr/bin/env python

"""
    imagebuilderpoll_function.py:
    AWS Step Functions State Machine Lambda Handler which 
    polls EC2 Image Builder to determine the availability of an AMI.
"""

import json
import logging
import os

import boto3


def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # print the event details
    logger.debug(json.dumps(event, indent=2))

    image_build_version_arn = event["image_build_version_arn"]

    imagebuilder_client = boto3.client('imagebuilder')
    response = imagebuilder_client.get_image(
        imageBuildVersionArn=image_build_version_arn
    )

    ami_state = response['image']['state']['status']
    event["ami_state"] = str(ami_state).upper()
    event["image_build_version_arn"] = image_build_version_arn

    return {
        'statusCode': 200,
        'body': event,
        'headers': {'Content-Type': 'application/json'}
    }
