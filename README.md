## Create Main Function for Cloud Control functionality

This repo contains main function for Cloud Control

### Excuses :)

Yes, I know, the code is awful. I will try to fix it one day. But this is not this day.

### Execution order

Resources from this repo should be created as third element of the platform.

1. Alexa Skill
2. AWS infrastructure
3. This repository

### Usage

This repository is ready to be run through TravisCI. 

First, lint tests are run against CloudFormation template and Python code, 
and CF stack is deployed to AWS account. The CF creates the Lambda function.

