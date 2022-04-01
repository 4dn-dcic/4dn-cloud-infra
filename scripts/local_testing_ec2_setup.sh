#!/bin/sh

### For Ubuntu-based EC2s as of March 2022 -drr

start_path=$PWD

current_python=$(which python)
python_version=3.7.12
expected_pyenv_dir="$HOME/.pyenv"
expected_poetry_dir="$HOME/.poetry"
expected_4dn_infra_dir="$HOME/4dn-cloud-infra"
expected_foursight_dir="$Home/foursight-cgap"

cd $HOME
sudo apt-get update
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
	libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev \
	libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev python-openssl

if [ ! -d $expected_pyenv_dir ]; then
    git clone https://github.com/pyenv/pyenv.git ~/.pyenv
    git clone https://github.com/pyenv/pyenv-virtualenv.git $(pyenv root)/plugins/pyenv-virtualenv

    export PATH="$HOME/.pyenv/bin:$PATH"
    eval "$(pyenv init --path)"
    eval "$(pyenv virtualenv-init -)"

    sed -i '1i eval "$(pyenv virtualenv-init -)"' ~/.bashrc
    sed -i '1i eval "$(pyenv init --path)"' ~/.bashrc
    sed -i '1i export PATH="$HOME/.pyenv/bin:$PATH"' ~/.bashrc
fi

if [ ! -d "$expected_pyenv_dir/versions/$python_version" ]; then
    pyenv install 3.7.12
fi

if [ ! -z $current_python ]; then
    pyenv global 3.7.12
fi

if [ ! -d $expected_poetry_dir ]; then
    curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python -
    source "$HOME/.poetry/env"
    sed -i '1i export PATH="$HOME/.poetry/bin:$PATH"' ~/.bashrc
fi

if [ ! -d $expected_4dn_infra_dir ]; then
    git clone https://github.com/4dn-dcic/4dn-cloud-infra.git
fi

if [ ! -d $expected_foursight_dir ]; then
    git clone https://github.com/dbmi-bgm/foursight-cgap
fi

cd 4dn-cloud-infra
if [ ! -f ".python-version" ]; then
    pyenv virtualenv 3.7.12 foursight-local
    pyenv local foursight-local
fi

# Install foursight locally via poetry
sed -i 's/.*foursight-cgap =.*/foursight-cgap = { path = "..\/foursight-cgap", develop = true }/' pyproject.toml

pip install --upgrade pip
poetry install

cd $start_path
