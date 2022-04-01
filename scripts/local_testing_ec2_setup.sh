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
eval "$(pyenv init --path)"
eval "$(pyenv virtualenv-init -)"

sed -i '1i eval "$(pyenv virtualenv-init -)"' ~/.bashrc
sed -i '1i eval "$(pyenv init --path)"' ~/.bashrc
sed -i '1i export PATH="$HOME/.pyenv/bin:$PATH"' ~/.bashrc

pyenv install 3.7.12
pyenv global 3.7.12
pyenv virtualenv 3.7.12 foursight-testing

curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python -
source $HOME/.poetry/env
sed -i '1i export PATH="$HOME/.poetry/bin:$PATH"' ~/.bashrc

git clone https://github.com/dbmi-bgm/foursight-cgap

cd 4dn-cloud-infra
pyenv local foursight-testing
# git checkout drr_foursight_ec2  # Switch to new local branch

# Install foursight locally via poetry
sed -i 's/.*foursight-cgap =.*/foursight-cgap = { path = "..\/foursight-cgap", develop = true }/' pyproject.toml

pyenv version
pip install --upgrade pip
pip install jupyter
poetry install
pip list

cd $start_path
