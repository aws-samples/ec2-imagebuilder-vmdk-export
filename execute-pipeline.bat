rem # Get project 
@echo off
setlocal enableextensions

set GIT_BRANCH_NAME=
for /F "delims=" %%n in ('git branch --show-current') do set "GIT_BRANCH_NAME=%%n"
if "%GIT_BRANCH_NAME%"=="" echo "Not a git branch!" && goto :EOF
echo "The current branch is %GIT_BRANCH_NAME%"

CDK_STACK_NAME="EC2ImageBuilderVmdkExport-%GIT_BRANCH_NAME%"
CFN_PIPELINE_OUTPUT_KEY="exportpipelinearn%GIT_BRANCH_NAME%"
CFN_SNS_TOPIC_OUTPUT_KEY="exportnotificationtopicarn%GIT_BRANCH_NAME%"

rem # print the assigned values
echo "GIT_BRANCH_NAME == %GIT_BRANCH_NAME%"
echo "CDK_STACK_NAME == %CDK_STACK_NAME%"
echo "CFN_PIPELINE_OUTPUT_KEY == %CFN_PIPELINE_OUTPUT_KEY%"
echo "CFN_SNS_TOPIC_OUTPUT_KEY == %CFN_SNS_TOPIC_OUTPUT_KEY%"

rem # grab the arns from the Cloudformation outputs
echo "Grabbing the EC2 Image Builder Pipeline ARN from Cloudformation Ouput key: %CFN_PIPELINE_OUTPUT_KEY%"
FOR /F "tokens=*" %%IMAGEBUILDER_PIPELINE_ARN IN ('aws cloudformation describe-stacks --stack-name %CDK_STACK_NAME% --query "Stacks[0].Outputs[?OutputKey=='%CFN_PIPELINE_OUTPUT_KEY%'].OutputValue" --output text') do (SET IMAGEBUILDER_PIPELINE_ARN=%%IMAGEBUILDER_PIPELINE_ARN)

echo "Grabbing the SNS Notification ARN from Cloudformation Ouput key: %CFN_SNS_TOPIC_OUTPUT_KEY%"
FOR /F "tokens=*" %%SNS_NOTIFICATION_ARN IN ('aws cloudformation describe-stacks --stack-name %CDK_STACK_NAME% --query "Stacks[0].Outputs[?OutputKey=='%CFN_SNS_TOPIC_OUTPUT_KEY%'].OutputValue" --output text') do (SET SNS_NOTIFICATION_ARN=%%SNS_NOTIFICATION_ARN)

echo "IMAGEBUILDER_PIPELINE_ARN == %IMAGEBUILDER_PIPELINE_ARN%"
echo "SNS_NOTIFICATION_ARN == %SNS_NOTIFICATION_ARN%"

rem # execute the EC2 Image Builder pipeline
echo "Executing the EC2 Image Builder Pipeline with ARN %IMAGEBUILDER_PIPELINE_ARN%"
FOR /F "tokens=*" %%IMAGE_BUILD_VERSION_ARN IN ('aws imagebuilder start-image-pipeline-execution --image-pipeline-arn %IMAGEBUILDER_PIPELINE_ARN% --query "imageBuildVersionArn" --output text') do (SET IMAGE_BUILD_VERSION_ARN=%%IMAGE_BUILD_VERSION_ARN)

echo "IMAGE_BUILD_VERSION_ARN == %IMAGE_BUILD_VERSION_ARN%"

rem # publish a message to the sns topic to begin the VMDK export process
echo "Publishing a message to SNS topic %SNS_NOTIFICATION_ARN% to begin the VMDK export process"
aws sns publish --topic-arn %SNS_NOTIFICATION_ARN% --message %IMAGE_BUILD_VERSION_ARN%