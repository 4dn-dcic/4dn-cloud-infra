#!/bin/bash -xe
sudo apt-get update
sudo apt-get install -y git make supervisor golang-go curl chrony
curl -O -L http://bit.ly/goofys-latest
sudo chmod +x /home/ubuntu/goofys-latest
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable"
sudo chmod +x /usr/local/bin/docker-compose
docker-compose --version
