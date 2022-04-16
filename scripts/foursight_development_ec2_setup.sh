#!/bin/sh

### For Ubuntu-based EC2s as of March 2022 -drr

start_path=$PWD

desired_python_version="3.7.12"
expected_4dn_infra_dir="$HOME/4dn-cloud-infra"
expected_foursight_dir="$HOME/foursight-cgap"
desired_pyproject_foursight_version='foursight-cgap = { path = "..\/foursight-cgap", develop = true }/' 
desired_pyproject_foursight_package='{ include = "foursight_development" }'

current_python=$(which python)
current_pyenv=$(which pyenv)
current_pyenv_versions=$(pyenv versions 2>/dev/null | grep -c $desired_python_version)
current_pyenv_virtualenv=$(pyenv virtualenv --version 2>/dev/null)
current_poetry=$(which poetry)

cd $HOME
sudo apt-get update
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
	libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev \
	libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev python-openssl

if [ -z $current_pyenv ]; then
    git clone https://github.com/pyenv/pyenv.git ~/.pyenv

    export PATH="$HOME/.pyenv/bin:$PATH"
    eval "$(pyenv init --path)"

    git clone https://github.com/pyenv/pyenv-virtualenv.git $(pyenv root)/plugins/pyenv-virtualenv

    eval "$(pyenv virtualenv-init -)"

    sed -i '1i eval "$(pyenv virtualenv-init -)"' ~/.bashrc
    sed -i '1i eval "$(pyenv init --path)"' ~/.bashrc
    sed -i '1i export PATH="$HOME/.pyenv/bin:$PATH"' ~/.bashrc
fi

if [ $current_pyenv_versions -eq 0 ]; then
    pyenv install $desired_python_version
fi

if [ -z $current_python ]; then
    pyenv global $desired_python_version
fi

if [ -z $current_poetry ]; then
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
pyenv virtualenv $desired_python_version foursight-local
pyenv local foursight-local
git_branch=$(git rev-parse --abbrev-ref HEAD)
if [ $git_branch = "master" ]; then
    git checkout -b foursight-local  # Prevent accidental master commits
fi

# Install foursight locally and create foursight_development package via poetry
develop_foursight_installed=$(grep -c "$desired_pyproject_foursight_version" pyproject.toml)
if [ $develop_foursight_installed -eq 0 ]; then
    sed -i "s/.*foursight-cgap =.*/foursight-cgap = $desired_pyproject_foursight_version }" pyproject.toml
fi

foursight_local_installed=$(grep -c "$desired_pyproject_foursight_package" pyproject.toml)
if [ $foursight_local_installed -eq 0 ]; then
    sed -i "s/.*{ include = \"src\" }.*/    { include = \"src\" },\n    $desired_pyproject_foursight_package" pyproject.toml
fi

pip install --upgrade pip
poetry install

cd $start_path
