#!/bin/bash

###################################################################
# Script Name     : execute-pipeline.sh
# Description     : Executes the EC2 Image Builder Pipeline to
#                   create an AMI and send a notification to
#                   a SNS topic to begin the VMExport process
#                   in which the AMI is converted to VDMK format.
# Args            :
# Author          : Damian McDonald
###################################################################

### <START> check if AWS credential variables are correctly set
if [ -z "${AWS_ACCESS_KEY_ID}" ]
then
      echo "AWS credential variable AWS_ACCESS_KEY_ID is empty."
      echo "Please see the guide below for instructions on how to configure your AWS CLI environment."
      echo "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html"
fi

if [ -z "${AWS_SECRET_ACCESS_KEY}" ]
then
      echo "AWS credential variable AWS_SECRET_ACCESS_KEY is empty."
      echo "Please see the guide below for instructions on how to configure your AWS CLI environment."
      echo "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html"
fi

if [ -z "${AWS_DEFAULT_REGION}" ]
then
      echo "AWS credential variable AWS_DEFAULT_REGION is empty."
      echo "Please see the guide below for instructions on how to configure your AWS CLI environment."
      echo "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html"
fi
### </END> check if AWS credential variables are correctly set

# Reset
NC='\033[0m'       # Text Reset

# Regular Colors
BLACK='\033[0;30m'        # Black
RED='\033[0;31m'          # Red
GREEN='\033[0;32m'        # Green
YELLOW='\033[0;33m'       # Yellow
BLUE='\033[0;34m'         # Blue
PURPLE='\033[0;35m'       # Purple
CYAN='\033[0;36m'         # Cyan
WHITE='\033[0;37m'        # White

# Get project values
GIT_BRANCH_NAME=$(git branch | sed -n -e 's/^\* \(.*\)/\1/p')
CDK_STACK_NAME="EC2ImageBuilderVmdkExport-${GIT_BRANCH_NAME}"
CFN_PIPELINE_OUTPUT_KEY="exportpipelinearn${GIT_BRANCH_NAME}"
CFN_SNS_TOPIC_OUTPUT_KEY="exportnotificationtopicarn${GIT_BRANCH_NAME}"

# print the assigned values
echo -e "${NC}GIT_BRANCH_NAME == ${GREEN}${GIT_BRANCH_NAME}${NC}"
echo -e "${NC}CDK_STACK_NAME == ${GREEN}${CDK_STACK_NAME}${NC}"
echo -e "${NC}CFN_PIPELINE_OUTPUT_KEY == ${GREEN}${CFN_PIPELINE_OUTPUT_KEY}${NC}"
echo -e "${NC}CFN_SNS_TOPIC_OUTPUT_KEY == ${GREEN}${CFN_SNS_TOPIC_OUTPUT_KEY}${NC}"

# grab the arns from the Cloudformation outputs
echo -e "${NC}Grabbing the EC2 Image Builder Pipeline ARN from Cloudformation Ouput key: ${GREEN}${CFN_PIPELINE_OUTPUT_KEY}${NC}"
IMAGEBUILDER_PIPELINE_ARN=$(aws cloudformation describe-stacks --stack-name ${CDK_STACK_NAME} --query "Stacks[0].Outputs[?OutputKey=='${CFN_PIPELINE_OUTPUT_KEY}'].OutputValue" --output text)

echo -e "${NC}Grabbing the SNS Notification ARN from Cloudformation Ouput key: ${GREEN}${CFN_SNS_TOPIC_OUTPUT_KEY}${NC}"
SNS_NOTIFICATION_ARN=$(aws cloudformation describe-stacks --stack-name ${CDK_STACK_NAME} --query "Stacks[0].Outputs[?OutputKey=='${CFN_SNS_TOPIC_OUTPUT_KEY}'].OutputValue" --output text)

echo -e "${NC}IMAGEBUILDER_PIPELINE_ARN == ${GREEN}${IMAGEBUILDER_PIPELINE_ARN}${NC}"
echo -e "${NC}SNS_NOTIFICATION_ARN == ${GREEN}${SNS_NOTIFICATION_ARN}${NC}"

# execute the EC2 Image Builder pipeline
echo -e "${NC}Executing the EC2 Image Builder Pipeline with ARN ${GREEN}${IMAGEBUILDER_PIPELINE_ARN}${NC}"
IMAGE_BUILD_VERSION_ARN=$(aws imagebuilder start-image-pipeline-execution --image-pipeline-arn ${IMAGEBUILDER_PIPELINE_ARN} --query "imageBuildVersionArn" --output text)

echo -e "${NC}IMAGE_BUILD_VERSION_ARN == ${GREEN}${IMAGE_BUILD_VERSION_ARN}${NC}"

# publish a message to the sns topic to begin the VMDK export process
echo -e "${NC}Publishing a message to SNS topic ${GREEN}${SNS_NOTIFICATION_ARN}${NC} to begin the VMDK export process"
aws sns publish --topic-arn ${SNS_NOTIFICATION_ARN} --message ${IMAGE_BUILD_VERSION_ARN}