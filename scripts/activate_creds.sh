#!/bin/sh

if [ -L custom ]; then
    echo "A symbolic link exists for file 'custom'. It will be redefined."
    ls -dal custom
    rm custom
elif [ -e custom ]; then
    echo "File 'custom' exists but is not a symbolic link. You must fix this manually."
    exit 1
fi

ln -s $1 custom

