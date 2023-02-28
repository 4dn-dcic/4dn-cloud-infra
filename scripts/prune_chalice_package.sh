#!/bin/bash
# --------------------------------------------------------------------------------------------------
# Script to remove (prune) unnecessary cruft from the specified Chalice zip file.
# This was done when (2022-12-16) we reached the maximum (unzipped) size, 220476770 bytes,
# of a Chalice package to deploy in AWS. To do this we delete all files/directories within
# the zip file which look to be related to tests or example modules. The file is changed IN PLACE.
# --------------------------------------------------------------------------------------------------

if [ $# -ne 1 ]; then
    echo "usage: prune_chalice_package path-to-chalice-zip-file"
    exit 1
fi

CHALICE_PACKAGE_ZIP_FILE=`echo $(cd "$(dirname -- "$1")" >/dev/null; pwd -P)/$(basename -- "$1")`

if [ ! -f ${CHALICE_PACKAGE_ZIP_FILE} ]; then
    echo "prune_chalice_package: file not found - $CHALICE_PACKAGE_ZIP_FILE"
    exit 2
fi

TMP_DIR=/tmp
YYYYMMDDhhmmss=`date +%Y%m%d%H%M%S`
TMP_CHALICE_PACKAGE_DIR=${TMP_DIR}/.chalice_package_prune_${YYYYMMDDhhmmss}
TMP_CHALICE_PACKAGE_FILE=${TMP_DIR}/.chalice_package_prune_${YYYYMMDDhhmmss}.zip
TMP_LOG_FILE=${TMP_DIR}/.chalice_package_prune_${YYYYMMDDhhmmss}.log

CHALICE_PACKAGE_SIZE=`du -s -h $CHALICE_PACKAGE_ZIP_FILE | awk '{print $1}'`
echo "Pruning chalice package ($CHALICE_PACKAGE_SIZE): ${CHALICE_PACKAGE_ZIP_FILE}"
echo "Log file for this chalice prune process: $TMP_LOG_FILE"

mkdir ${TMP_CHALICE_PACKAGE_DIR}
cd ${TMP_CHALICE_PACKAGE_DIR}
unzip ${CHALICE_PACKAGE_ZIP_FILE} 2>&1 > $TMP_LOG_FILE

# PLEASE BE CAREFUL HERE:
# THIS below  ... the rm -rf ... looks understandably SCARY.
# We ASSUME we are in (i.e. our current directory is) the TEMPORARY
# directory (TMP_CHALICE_PACKAGE_DIR), which contains the contents
# of our unzipped Chalice deployement package, via the cd above.
# We will paranoia DOUBLE CHECK that this under /tmp first.
#
echo "Preparing to prune/delete cruft from chalice package."
if [[ `pwd` != "/tmp/"* ]]; then
    echo "ERROR: prune script has an error! In unexpected directory: `pwd`"
    exit 1
fi
echo "Deleting cruft from chalice package."
rm -rf `find . -name examples -type d`
rm -rf `find . -name tests -type d`
rm -rf `find . -name test -type d`
echo "Done deleting cruft from chalice package."

zip -r ${TMP_CHALICE_PACKAGE_FILE} . 2>&1 > $TMP_LOG_FILE
rm -rf ${TMP_CHALICE_PACKAGE_DIR}

mv -f ${TMP_CHALICE_PACKAGE_FILE} ${CHALICE_PACKAGE_ZIP_FILE}

CHALICE_PACKAGE_NEW_SIZE=`du -s -h $CHALICE_PACKAGE_ZIP_FILE | awk '{print $1}'`

echo "Done pruning chalice package ($CHALICE_PACKAGE_NEW_SIZE): ${CHALICE_PACKAGE_ZIP_FILE}"
