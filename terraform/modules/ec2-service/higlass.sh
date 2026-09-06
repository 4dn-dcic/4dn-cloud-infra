#!/bin/bash -xe
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common git
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable"
sudo apt update; apt-cache policy docker-ce
sudo apt install --assume-yes docker-ce
mkdir ~/hg-tmp
curl https://cgap-higlass.s3.amazonaws.com/hg-data/higlass-server-data.tar.gz --output higlass-server-data.tar.gz
tar -xzvf higlass-server-data.tar.gz --directory ~
sudo git clone https://github.com/dbmi-bgm/higlass-docker-setup
cd higlass-docker-setup
sudo -E ./start_production.sh