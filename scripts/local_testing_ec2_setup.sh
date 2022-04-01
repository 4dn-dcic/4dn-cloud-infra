#!/bin/sh

### For Ubuntu-based EC2s as of March 2022 -drr

start_path=$PWD
cd $HOME

sudo apt-get update
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
	libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev \
	libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev python-openssl

curl https://pyenv.run | bash

export PATH="$HOME/.pyenv/bin:$PATH"
sed -i '1i export PATH="$HOME/.pyenv/bin:$PATH"' ~/.bashrc
eval "$(pyenv init --path)"
sed -i '1i eval "$(pyenv init --path)"' ~/.bashrc
eval "$(pyenv virtualenv-init -)"
sed -i '1i eval "$(pyenv virtualenv-init -)"' ~/.bashrc

pyenv install 3.7.12
pyenv global 3.7.12
pyenv virtualenv 3.7.12 foursight-testing

curl -sSL https://install.python-poetry.org | python -
export PATH="/home/ubuntu/.local/bin:$PATH"
sed -i '1i export PATH="/home/ubuntu/.local/bin:$PATH"' ~/.bashrc

git clone https://github.com/dbmi-bgm/foursight-cgap

cd 4dn-cloud-infra
# git checkout drr_foursight_ec2  # Switch to new local branch
pyenv local foursight-testing

# Install foursight locally via poetry
sed -i 's/.*foursight-cgap =.*/foursight-cgap = { path = "..\/foursight-cgap", develop = true }/' pyproject.toml

poetry update
pip install --upgrade pip
pip install jupyter  # Poetry not installing jupyter as nicely

cd $start_path
