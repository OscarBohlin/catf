#!/usr/bin/env python
#
# Copyright (C) 2023 Oscar Bohlin
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
Given two target files, produce an output directory showcasing the differences between them.
The comparison is deep and recursive, meaning any unpackable file will be extracted and compares
leading to the minimum form of changes between the two target files.

To compare to target files:
Usage: catf.py compare [options] target1 target2

To extract build information from one target file:
Usage: catf.py extract [options] target_file

"""


import os
import sys
import argparse
import time
import filecmp
import zipfile

ZIP_FILENAME_1 = ""
ZIP_FILENAME_2 = ""

TMP_DIRECTORY = "/tmp"
ROOT_COMPARISON = f"{TMP_DIRECTORY}/comparison"
OUTPUT_DIR = "diffs"
QUIET = False
GRADLEW_PATH = "~/gradlew"


all_commands = []
uncomparable_files = []
apk_files = []


DIFF_ARGS = "-qraNwB --no-dereference"

"""
DIFF_ARGS:

    -q (brief), puts output on format File <file1> and <file2> differs
        makes it easy to pipe to awk and get just "<file1> <file2>"

    -r (rcursive), include subdirectories in search

    -a (text), treat all files as text-files to allow output for binary files

    -N, treat absent files as empty, in case of one target files having less (or more)
        files than the other. This does however not appear to work
    -w (ignore whitespace) any whitespace is irrlevant to the functionality of the target files
        some files differ simply on blank lines, therefore we ignore all whitespace
    -B (ignore empty lines) see above

    --no-dereference, the target files includes symbolic links for
        mounting other files, since they don't lead to a file that
        exists diff will cause an error therefore ignore

    --unidirectional-new-file, unsure about this one
"""



class UncomparableFilesException(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def compare_target_files(zip1: str, zip2: str, force_clean: bool) -> dict:
    """
    compare two target files
    returns a dict where keys are path from inside image, and values are files on disk
    for that path
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2
    global uncomparable_files
    global OUTPUT_DIR

    all_diffs = {}
    zip1_dst = f"{TMP_DIRECTORY}/target-files/{ZIP_FILENAME_1}"
    zip2_dst = f"{TMP_DIRECTORY}/target-files/{ZIP_FILENAME_2}"

    if force_clean:
        make_clean(zip1_dst, zip2_dst)

    if not dir_exists(f"{TMP_DIRECTORY}/target-files"):
        run_shell_command(f"mkdir -p {TMP_DIRECTORY}/target-files")

    unzip_target_files(zip1, zip2, zip1_dst, zip2_dst)
    initial_diff = diff(zip1_dst, zip2_dst)

    for file_pair in initial_diff:
        file1 = file_pair.split(" ")[0]
        file2 = file_pair.split(" ")[1]
        parent_dir = get_relative_path(file1)

        try:
            diffs = compare_files(file1, file2, parent_dir)
            all_diffs.update(diffs)

        except UncomparableFilesException as ex:
            uncomparable_files += [f"{file1} {file2}"]
            print(ex)
            sys.exit(1)

    return all_diffs




def unzip_target_files(zip1_path: str, zip2_path: str, zip1_dst: str, zip2_dst: str):
    """
    unzip the two target files
    takes input source and destination
    if the destination already exists it is assumed no further extracting has to be done
    """
    if not dir_exists(zip1_dst):
        print(f"unzipping {zip1_path} ...")
        unzip(zip1_path, zip1_dst)

    else:
        print(f"found {zip1_path} unpacked, reusing")

    if not dir_exists(zip2_dst):
        print(f"unzipping {zip2_path} ...")
        unzip(zip2_path, zip2_dst)

    else:
        print(f"found {zip2_path} unpacked, reusing")

def compare_files(file1: str, file2: str, parent_dir: str) -> dict:
    """
    compare two files content, unpack any found "unpackable" files and recursively unpack further
    parent_dir: the *desired* path of the files being compared

    returns a dict where keys are the paths from within the target file and
    values are a list of all files that differ for that parent_path
    """
    diffs_dict = {}
    compare_files_recursive(file1, file2, parent_dir, diffs_dict)
    return diffs_dict


def compare_files_recursive(file1: str, file2: str, parent_dir: str, all_diffs: dict) -> list:
    """
    compare two files recursively, unpack as far as you can and return
    the full list of files that differ
    """
    global uncomparable_files
    global apk_files

    ext1 = extension(file1)
    ext2 = extension(file2)
    ext = ext1[1:]

    if not ext1 == ext2:
        print_error(f"cannot compare '{ext1}' and '{ext2}' files. Not the same extension!")
        sys.exit(1)

    diffs = []
    print(f"comparing {parent_dir} ...")

    if ext == "img":
        diffs = compare_image_files(file1, file2)

    elif is_text_file(file1):
        diffs = [f"{file1} {file2}"]

    elif ext == "apex":
        diffs = compare_apex_files(file1, file2)

    elif ext == "capex":
        diffs = compare_capex_files(file1, file2)

    elif ext == "apk":
        # store where the apk files are on disk so we can find them later
        # for cert comparisons
        apk_files.append(f"{file1} {file2}")
        diffs = compare_apk_files(file1, file2)

    elif ext == "zip":
        diffs = compare_zip_files(file1, file2)

    elif ext == "gz":
        diffs = compare_gz_files(file1, file2)

    elif ext == "lz4":
        diffs = compare_lz4_files(file1, file2)

    elif ext == "ext4":
        diffs = compare_ext4_files(file1, file2)

    else:
        print(f"unsupported file! {file1}")
        all_diffs[parent_dir] = [f"{file1} {file2}"]
        return parent_dir, [f"{file1} {file2}"]

    further_extractable = can_extract_further(diffs)
    # some files (ie .img files) generate more comparable files
    # that we must also compare
    new_diffs_to_compare = list(set(further_extractable) - set(uncomparable_files))

    # we now have file pairs that exist in both
    # diff and further_extractable and we will have duplicates if we're not careful
    previous_diffs = list(set(diffs) - set(new_diffs_to_compare))

    if len(previous_diffs) > 0:
        all_diffs[parent_dir] = previous_diffs

    # no new files that we can extract furter
    if len(new_diffs_to_compare) == 0:
        return parent_dir, diffs



    new_diffs = []

    for file_pair in new_diffs_to_compare:
        file1 = file_pair.split(" ")[0]
        file2 = file_pair.split(" ")[1]

        new_parent_dir = get_new_parent_dir(file1, parent_dir)
        (_, diffs) = compare_files_recursive(file1, file2, new_parent_dir, all_diffs)
        new_diffs += diffs

    return None, (previous_diffs + new_diffs)

def get_new_parent_dir(path: str, current_parent: str) -> str:
    """
    Given parent directory and path return the new parent directory
    """
    relative_name = get_relative_path(path)
    fname = get_filename(path)

    findex = current_parent.rfind("/")
    parent_file = current_parent[findex + 1:]
    parent_dir = current_parent[:findex]
    new_parent = ""

    # check if the file part of the parent dir is included in the relative name
    # is so, then we take the parent dir and add relative fname
    if parent_file in relative_name:
        new_parent = f"{parent_dir}/{relative_name}"
    else:
        new_parent = f"{current_parent}/{fname}"

    return new_parent


def can_extract_further(diffs: list) -> list:
    """
    some file extensions can be extracted further, (ie) zip files.
    this function returns a subset of all files provided of which can be further exrtractable
    """
    extractable_extensions = [".apex", ".capex", ".img", ".apk", ".zip", ".gz", ".lz4", ".ext4"]
    further_extractable = []
    for file_pair in diffs:
        file1 = file_pair.split(" ")[0]
        ext = extension(file1)

        if ext in extractable_extensions:
            further_extractable.append(file_pair)

    return further_extractable

def compare_image_files(img1: str, img2: str) -> list:
    """
    .img files are different
    they cannot be unpacked by normal tools such as
    zip, tar, gzip et cetera

    some android sparse file can be converted to a normal img file via simg2img
    but far form all of them
    gradlew is a tool to manipulate boot files, and work on alot of different files:
    https://github.com/cfig/Android_boot_image_editor

    Process of comparing img files are:
        Move the first file to gradlew installation but
        make sure to clean up any previous unsucessfull builds

        Run gralew unpack and remove the .log file before moving results
        The log file is only created when it runs 7z, ie the system.img partition

        Move the other imagefile and repeat process
        Make sure to clean up any files.

        Gradlew creates log files frmo uuid:s, not much to do about.
    """
    imgfile = get_filename(img1)
    img1_dst = f"{ROOT_COMPARISON}/imgs/{imgfile}/{ZIP_FILENAME_1}"
    img2_dst = f"{ROOT_COMPARISON}/imgs/{imgfile}/{ZIP_FILENAME_2}"

    # the userdata partition is empty when compiled
    # and may not be inside the target files on signed build
    # therefore we can safely skip
    # Sometimes it contains metadata files but not all the time.
    if imgfile == "userdata.img":
        return []

    # gradlew cannot unpack theese images, do them using 7z
    if imgfile in ("ramdisk.img", "product.img", "system.img"):
        use_sim2img = imgfile != "ramdisk.img"
        extract_7z_files(img1, img2, img1_dst, img2_dst, use_sim2img)
        return diff(img1_dst, img2_dst)


    global GRADLEW_PATH
    gradlew = GRADLEW_PATH
    gradlew_bin = f"{gradlew}/gradlew"
    gradlew_build = f"{gradlew}/build/unzip_boot/"

    rm_gradlew_log = f"rm -f {gradlew}/build/unzip_boot/*.log"

    run_shell_command(f"rm -rf {img1_dst} {img2_dst}")
    run_shell_command(f"mkdir -p {img1_dst} {img2_dst}")
    run_shell_command(f"rm -f {gradlew}/*.img && cp {img1} ~/gradlew")
    run_shell_command(f"cd {gradlew} && {gradlew_bin} unpack 2> /dev/null && {rm_gradlew_log}")
    run_shell_command(f"mv {gradlew_build} {img1_dst}")

    run_shell_command(f"rm -f {gradlew}/*.img && cp {img2} ~/gradlew")
    run_shell_command(f"cd {gradlew} && {gradlew_bin} unpack 2> /dev/null && {rm_gradlew_log}")
    run_shell_command(f"mv {gradlew_build} {img2_dst}")
    run_shell_command(f"rm -f {gradlew}/*.img")

    return diff(img1_dst, img2_dst)


def compare_apex_files(apex1: str, apex2: str) -> list:
    """
    Compare two apex files
    """
    # Process of comparing apex files:
    # 1. Unzip the apex file as if it were a normal zip file
    # 2. unpack the .gz file
    # 3. make a diff of the two folders

    global ZIP_FILENAME_1
    global ZIP_FILENAME_2

    apex_module = get_filename(apex1)
    apex_target_dir = f"{ROOT_COMPARISON}/{apex_module}"

    apex1_dst = f"{apex_target_dir}/{ZIP_FILENAME_1}"
    apex2_dst = f"{apex_target_dir}/{ZIP_FILENAME_2}"

    run_shell_command(f"mkdir -p {apex1_dst} {apex2_dst}")


    if dir_exists(apex1_dst):
        run_shell_command(f"rm -rf {apex1_dst}/*")

    if dir_exists(apex2_dst):
        run_shell_command(f"rm -rf {apex2_dst}/*")

    unzip(apex1, apex1_dst)
    unzip(apex2, apex2_dst)

    notice_file1 = f"{apex1_dst}/assets/NOTICE.html.gz"
    notice_file2 = f"{apex2_dst}/assets/NOTICE.html.gz"

    if file_exists(notice_file1) and file_exists(notice_file2):
        # gzip -d removes the original file after unpacking
        run_shell_command(f"gzip -d {notice_file1}")
        run_shell_command(f"gzip -d {notice_file2}")


    return diff(apex1_dst, apex2_dst)


def compare_capex_files(capex1, capex2) -> list:
    """
    Compare two capex files
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2

    original_apex1 = f"{capex1}/original_apex"
    original_apex2 = f"{capex2}/original_apex"
    capex_module = get_filename(capex1)

    # Process of comparing capex files:
    # 1. Unzip the apex as if it were a normal zip file
    # 2. Extract the original_apex file to a subfolder of the extracted caped file
    # 3. Make sure the original_apex file and the .capex file are not included in the diff
    # 4. make a diff of the two folders

    capex_target_dir = f"{ROOT_COMPARISON}/{capex_module}"

    capex1_dst = f"{capex_target_dir}/{ZIP_FILENAME_1}"
    capex2_dst = f"{capex_target_dir}/{ZIP_FILENAME_2}"



    # Step 1
    #if dir_exists(capex1_dst):
    run_shell_command(f"rm -rf {capex1_dst}")

    #if dir_exists(capex2_dst):
    run_shell_command(f"rm -rf {capex2_dst}")

    run_shell_command(f"mkdir -p {capex1_dst} {capex2_dst}")
    unzip(capex1, capex1_dst)
    unzip(capex2, capex2_dst)


    original_apex1 = f"{capex1_dst}/original_apex"
    original_apex2 = f"{capex2_dst}/original_apex"

    original_apex1_file = f"{original_apex1}.apex"
    original_apex2_file = f"{original_apex2}.apex"

    # Step 2
    run_shell_command(f"mv {original_apex1} {original_apex1_file}")
    run_shell_command(f"mv {original_apex2} {original_apex2_file}")


    unzip(original_apex1_file, original_apex1)
    unzip(original_apex2_file, original_apex2)

    # Step 3
    run_shell_command(f"rm {original_apex1_file}")
    run_shell_command(f"rm {original_apex2_file}")

    notice_file1 = f"{original_apex1}/assets/NOTICE.html.gz"
    notice_file2 = f"{original_apex2}/assets/NOTICE.html.gz"

    if file_exists(notice_file1) and file_exists(notice_file2):
        run_shell_command(f"gzip -d {notice_file1}")
        run_shell_command(f"gzip -d {notice_file2}")

    # Step 4
    files_that_differ = diff(capex1_dst, capex2_dst)


    return files_that_differ



def compare_apk_files(apk1: str, apk2: str) -> list:
    """
    compare two apk files
    """

    # APK files can be unziped and compared as normal zip files
    rpath = get_relative_path(apk1)

    apk_target = f"{ROOT_COMPARISON}/apks/{rpath}"
    apk1_dst = f"{apk_target}/{ZIP_FILENAME_1}"
    apk2_dst = f"{apk_target}/{ZIP_FILENAME_2}"

    run_shell_command(f"rm -rf {apk1_dst} {apk2_dst}")
    run_shell_command(f"mkdir -p {apk1_dst} {apk2_dst}")

    unzip(apk1, apk1_dst)
    unzip(apk2, apk2_dst)

    return diff(apk1_dst, apk2_dst)



def compare_zip_files(zip1: str, zip2: str) -> list:
    """
    unpack and compare two zip files
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2

    rpath = get_relative_path(zip1)
    zipfile_target_dir = f"{ROOT_COMPARISON}/zip/{rpath}"

    zip1_dst = f"{zipfile_target_dir}/{ZIP_FILENAME_1}"
    zip2_dst = f"{zipfile_target_dir}/{ZIP_FILENAME_2}"

    run_shell_command(f"rm -rf {zip1_dst} {zip2_dst}")
    run_shell_command(f"mkdir -p {zip1_dst} {zip2_dst}")

    unzip(zip1, zip1_dst)
    unzip(zip2, zip2_dst)

    return diff(zip1_dst, zip2_dst)


def compare_gz_files(gz1: str, gz2: str) -> list:
    """
    unpack and return the difference between two gz files
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2

    gz_filename = get_filename(gz1)

    gz_target_dir = f"{ROOT_COMPARISON}/gz/{gz_filename}"
    gz1_dst = f"{gz_target_dir}/{ZIP_FILENAME_1}"
    gz2_dst = f"{gz_target_dir}/{ZIP_FILENAME_2}"

    gz1_target = f"{gz1_dst}/{get_filename(gz1)}"
    gz2_target = f"{gz2_dst}/{get_filename(gz2)}"

    run_shell_command(f"mkdir -p {gz1_dst} {gz2_dst}")
    run_shell_command(f"cp {gz1} {gz1_dst}")
    run_shell_command(f"cp {gz2} {gz2_dst}")

    run_shell_command(f"gzip -d {gz1_target}")
    run_shell_command(f"gzip -d {gz2_target}")

    return diff(gz1_dst, gz2_dst)


def compare_lz4_files(lz41: str, lz42: str) -> list:
    """
    unpack and return the difference between two lz4 files
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2

    lz4_filename = get_filename(lz41)
    lz4_target_dir = f"{ROOT_COMPARISON}/lz4/{lz4_filename}"
    lz41_dst = f"{lz4_target_dir}/{lz4_filename}/{ZIP_FILENAME_1}"
    lz42_dst = f"{lz4_target_dir}/{lz4_filename}/{ZIP_FILENAME_2}"
    lz41_target = f"{lz41_dst}/{lz4_filename}"
    lz42_target = f"{lz42_dst}/{lz4_filename}"

    run_shell_command(f"rm -rf {lz41_dst} {lz42_dst}")
    run_shell_command(f"mkdir -p {lz41_dst} {lz42_dst}")
    run_shell_command(f"lz4 -q {lz41} -dc > {lz41_target}")
    run_shell_command(f"lz4 -q {lz42} -dc > {lz42_target}")
    run_shell_command(f"rm -f {lz41_target} {lz42_target}")

    return diff(lz41_dst, lz42_dst)




def compare_ext4_files(ext41: str, ext42: str) -> list:
    """
    unpack and return the difference between two .ext4 files
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2

    ext4_filename = get_filename(ext41)
    ext4_target_dir = f"{ROOT_COMPARISON}/ext4/{ext4_filename}"
    ext41_dst = f"{ext4_target_dir}/{ZIP_FILENAME_1}"
    ext42_dst = f"{ext4_target_dir}/{ZIP_FILENAME_2}"


    extract_7z_files(ext41, ext42, ext41_dst, ext42_dst)
    return diff(ext41_dst, ext42_dst)


def extract_7z_files(file1: str, file2: str, target1: str, target2: str, use_sim2img: bool = False):
    """
    extract the supplied files using 7z to their target destination
    use_sim2img: wether to use the simg2img tool before extracting, needed
        for some images like the product.img file
    """

    file1_fullname = get_filename(file1)
    file2_fullname = get_filename(file2)

    #filename_without_extension = get_basename(file1)
    run_shell_command(f"rm -rf {target1} {target2}")
    run_shell_command(f"mkdir -p {target1} {target2}")
    run_shell_command(f"cp {file1} {target1}")
    run_shell_command(f"cp {file2} {target2}")


    if use_sim2img:
        extract_file1 = f"simg2img {file1_fullname} {file1_fullname}.iso && 7z -bb0 -bd x {file1_fullname}.iso"
        extract_file2 = f"simg2img {file2_fullname} {file2_fullname}.iso && 7z -bb0 -bd x {file2_fullname}.iso"

        run_shell_command(f"cd {target1} && {extract_file1} > /dev/null && rm -f {file1_fullname}* *.log")
        run_shell_command(f"cd {target2} && {extract_file2} > /dev/null && rm -f {file2_fullname}* *.log")
    else:
        run_shell_command(f"cd {target1} && 7z -bb0 -bd x {file1_fullname} > /dev/null && rm -f {file1_fullname} *.log")
        run_shell_command(f"cd {target2} && 7z -bb0 -bd x {file2_fullname} > /dev/null && rm -f {file2_fullname} *.log")

    # don't forget to remove the {filename}.log file generated by 7z!
        run_shell_command(f"rm -f {target1}/*.log {target2}/*.log")



def get_progname() -> str:
    return get_filename(sys.argv[0])


def print_error(cause: str):
    """
    prints an error message to stderr
    format: argv[0]: error: $cause
    """
    prog = get_progname()
    sys.stderr.write(f"{prog}: error: {cause}")



def extension(path: str) -> str:
    """
    return the extension of a given file
    """
    _, ext = os.path.splitext(path)
    return ext

def get_basename(path: str) -> str:
    """
    return the filename without extension of a given file
    """
    fname = os.path.basename(path)
    basename, _ = os.path.splitext(fname)
    return basename


def get_filename(path: str) -> str:
    """
    returns the name of the file from the provied path
    """
    return os.path.basename(path)

def full_filename(path: str) -> str:
    """
    returns the name of the file from the provied path
    """
    return get_filename(path)

def dir_exists(path: str) -> bool:
    """
    returns True if the supplied path exists and is a directory
    """
    return os.path.isdir(path)

def file_exists(path: str) -> bool:
    """"
    returns True if the supplied path exists and is a file
    """
    return os.path.isfile(path)


def files_are_equal(file1: str, file2: str) -> bool:
    """
    returns True if the two paths points to files that are identical
    """
    try:
        equal = filecmp.cmp(file1, file2, shallow=False)
        return equal
    except FileNotFoundError:
        return False


def write_to_file(content: str, path: str):
    """
    write supplied content to given file
    """
    fp = open(path, "w")
    fp.write(content)
    fp.close()

def append_to_file(content: str, path: str):
    """
    append supplied content to given file
    """
    fp = open(path, "a")
    fp.write(content)
    fp.close()

def read_from_file(path: str) -> list:
    """
    Read content from files and return each line as a list item
    """
    fp = open(path, "r")
    content = fp.readlines()
    fp.close()
    return content


def get_file_type(path: str) -> str:
    """
    Returns the full filetype of the supplied file
    equal to runing `file path`
    """

    awk_command = "awk -F \": \" '{print $2}'"
    output, _ = run_shell_command(f"file {path} | {awk_command}")
    return output[0]

def is_text_file(path: str) -> bool:
    """
    returns True if the supplied file is a text file
    """
    file_type = get_file_type(path).lower()

    # this isn't the most robust solution
    # but it will work for this case
    return "text" in file_type


def is_lz4_file(path: str) -> bool:
    """
    returns true if the privded path leads to a lz4 compressed file
    """

    file_type = get_file_type(path).lower()
    return "lz4 compressed data" in file_type

def sort_files(file1: str, file2: str):
    """
    Given two files, sort their content
    NOTE: this will rewrite the file!
    """
    f1_content = read_from_file(file1)
    f2_content = read_from_file(file2)

    f1_content.sort()
    f2_content.sort()

    write_to_file("".join(f1_content), file1)
    write_to_file("".join(f2_content), file2)


def list_to_str(the_list: list) -> str:
    """
    convert a list of strings to a single string
    """
    return "\n".join(the_list) + "\n"


def remove_newlines(input_list: list) -> list:
    """
    remove newlines for each string in a list
    """
    new_list = []
    for line in input_list:
        while line.find("\n") != -1:
            line = line.replace("\n", "")

        new_list.append(line)
    return new_list



def run_shell_command(cmd: str) -> tuple:
    """
    run a shell command
    command is printed to stdout and stored in `all_commands`

    returns the output of the command as a list of each output-line
    raises: UncomparableFilesException if the command did not exit successfully
    """
    global all_commands
    global QUIET

    if not QUIET:
        print(cmd)

    all_commands.append(cmd)

    cmd_output = os.popen(cmd)
    list_output = cmd_output.readlines()
    exit_code = cmd_output.close()

    if not shell_successfull(cmd, exit_code):
        error_msg = f"command '{cmd}' exited with status: {exit_code}"
        raise UncomparableFilesException(error_msg)


    return list_output, exit_code


def shell_successfull(cmd: str, exit_code) -> bool:
    """
    determines if the command was successfull or not
    diff and grep will have a non-zero exit code even if nothing was wrong
    """
    prog = cmd.split(" ")[0]
    if exit_code is None:
        return True
    if prog in ("grep", "diff"):
        return exit_code != 2

    return exit_code == 0




def diff(path1: str, path2: str) -> list:
    """
    Returns the difference between two directories
    return format: ["<file1> <file2>"]
    the files (on disk) is seperated by a space
    """

    awk_cmd = f"awk '{{print $2 \" \" $4}}'"
    diff_cmd = f"diff {DIFF_ARGS} {path1} {path2}"
    full_cmd = f"{diff_cmd} | {awk_cmd}"
    output, _ = run_shell_command(full_cmd)

    return remove_newlines(output)



#def text_diff(path1: str, path2: str) -> str:
#    """
#    Get the text difference from two files, ignore whitespace
#    """
#    diff_cmd = f"diff -awB --color=always {path1} {path2}"
#    output, _ = run_shell_command(diff_cmd)

    # convert diff to single string
#    without_newlines = remove_newlines(output)
#    as_string = list_to_str(without_newlines)
#    return as_string



def unzip(src: str, dst: str):
    """
    unzip a file to a given destination using `unzip`
    src: file to unzip
    dst: where to extract
    exits if unzip was unsuccessfull
    """

    cmd = f"unzip -q {src} -d {dst}"
    _, exit_code = run_shell_command(cmd)

    if not shell_successfull(cmd, exit_code):
        print_error(f"unable unzipping file {src} to {dst}, exit code: {exit_code}")
        sys.exit(1)


def get_apk_cert_diff(apk2: str, apk1: str) -> str:
    """
    Extract certificate difference betw
    apk2: path to second apk fileeen two apk files
    apk1: path to first apk file
    runs diff `apksigner verify apk1` and `apksiger verify apk2`
    and returns diff as a single string
    """
    apk_filename = get_filename(apk1)

    certinfo1_target = f"{ROOT_COMPARISON}/apk-certs/{apk_filename}"
    certinfo2_target = f"{ROOT_COMPARISON}/apk-certs/{apk_filename}"
    certinfo1_dst = f"{certinfo1_target}/1"
    certinfo2_dst = f"{certinfo2_target}/2"


    # tried using process substution but it didn't work because the
    # output contains "(" and ")" which escapes the bash command
    run_shell_command(f"mkdir -p {certinfo1_target} {certinfo2_target}")
    run_shell_command(f"apksigner verify -v --print-certs {apk1} > {certinfo1_dst}")
    run_shell_command(f"apksigner verify -v --print-certs {apk2} > {certinfo2_dst}")

    # we don't use DIFF_ARGS because it's important not to use -q flag
    # as it would just print the file names
    cert_diff, _ = run_shell_command(f"diff --color=always -wBa {certinfo1_dst} {certinfo2_dst}")

    return list_to_str(remove_newlines(cert_diff))


def get_apkname_from_cert_path(certpath: str) -> str:
    """
    given a path to a /META-INF/CERT.RSA certificate,
    return the corresponding APK name
    """
    metainf_index = certpath.index("/META-INF/")
    path_without_metainf = certpath[:metainf_index]

    # we don't need the / since start index is inclusive
    apkname_indexstart = path_without_metainf.rfind("/") + 1
    apkname = path_without_metainf[apkname_indexstart:]

    return apkname

# returns a tuple of (file1, file2)
# of where theese files are stored on disk
def get_apk_disk_files_from_name(apkname: str) -> tuple:
    """
    given a apkname return their path on disk as in (file1, file2)
    """
    global apk_files
    for apk_file_pair in apk_files:
        apk1 = apk_file_pair.split(" ")[0]
        apk2 = apk_file_pair.split(" ")[1]

        if apkname in apk1 and apkname in apk2:
            return (apk1, apk2)
    return None


def create_diff_tree(full_file_list: list) -> list:
    """
    Create a tree representation of all files that differ with paths
    as they are located frmo within the target files

    If the file IMAGES/system.img/build.prop differ the output of the diff command
    will be in the $OUTPUT/IMAGES/system.img/build.prop.diff

    Sometimes apk files will differ on certificates, if this is the case
    then we use a *preatty diff* tool for displaying the different sha256-digest sum
    from the apksigner tool by Google
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2

    diff_tree = []
    nonempty_diffs = []

    for file_tuple in full_file_list:
        path = file_tuple[0]
        file1 = file_tuple[1]
        file2 = file_tuple[2]
        target_dir, target_file = get_target_dir_and_file_from_path(path)

        the_diff = ""
        text_file = is_text_file(file1)

        if not text_file:
            the_diff += "File location on disk:\n"
            the_diff += f"{ZIP_FILENAME_1}: {file1}\n"
            the_diff += f"{ZIP_FILENAME_2}:  {file2}\n\n"

        file_diff = ""

        # map files are huge and may contain similar lines
        # sort them before comparison to get minimal changes
        if ".map" in path:
            sort_files(file1, file2)

        # the diff for CERT.RSA files doesen't say much
        # instead we use the apksiger tool to compare the SHA256 digest sum for the certificate
        # to create a more easily undertandable diff
        if "CERT.RSA" in path and ".apk" in path:
            apk1_path, apk2_path = get_apk_disk_files_from_name(get_apkname_from_cert_path(path))
            file_diff += get_apk_cert_diff(apk1_path, apk2_path)

        else:
            args = "-NaurwB" if text_file else "-wB"
            (output, _) = run_shell_command(f"diff {args} --color=always {file1} {file2}")
            file_diff += list_to_str(remove_newlines(output))

        if file_diff.strip() == "":
            continue

        final_diff = create_diff_text(file_diff, the_diff, text_file)
        diff_tree.append((target_dir, target_file, final_diff, file_tuple))
        nonempty_diffs.append(file_tuple)

    return diff_tree, nonempty_diffs


def write_diff_tree(files_to_write: list):
    """
    write the diff tree to file system
    """
    for file_tuple in files_to_write:

        target_dir = file_tuple[0]
        target_file = file_tuple[1]
        diff_to_write = file_tuple[2]
        run_shell_command(f"mkdir -p {target_dir}")
        write_to_file(diff_to_write, target_file)

def create_diff_text(file_diff: str, the_diff: str, text_file: bool) -> str:
    """
    Create the text that goes inside the .diff file on filesystem
    """
    final_diff = ""

    if text_file:
        final_diff = file_diff
    else:
        final_diff = the_diff + "\n" + file_diff + "\n"

    return final_diff








def get_relative_path(path: str):
    """
    returns the relative path for a given file on disk

    unpacking does not happen 'in place', rather the targeted file
    is moved to another directory, unpacked and then diffed leaving the file path
    for the diffe'd files something like
    /tmp/comparison/zip/<module>/<zipfilename1>/and/then/the/path
    and this function returns and/then/the/path
    """

    global TMP_DIRECTORY
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2
    global ROOT_COMPARISON

    rpath = path.replace(f"{TMP_DIRECTORY}/target-files/{ZIP_FILENAME_1}", "")
    rpath = rpath.replace(f"{TMP_DIRECTORY}/target-files/{ZIP_FILENAME_2}", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/apks", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/capex", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/apex", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/ext4", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/lz4", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/imgs", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/gz", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}/zip", "")
    rpath = rpath.replace(f"{ZIP_FILENAME_1}", "")
    rpath = rpath.replace(f"{ZIP_FILENAME_2}", "")
    rpath = rpath.replace(f"{ROOT_COMPARISON}", "")


    # path created by Android_boot_image_editor (gradlew)
    rpath = rpath.replace(f"unzip_boot", "")


    while rpath.find("//") != -1:
        rpath = rpath.replace("//", "/")


    if rpath.startswith("/"):
        rpath = rpath[1:]

    return rpath



def get_full_path(parent_path: str, path: str) -> str:
    """
    Final step
    """
    relative_path = get_relative_path(path)
    relative_dirs = relative_path.split("/")
    full_path = parent_path

    for directory in relative_dirs:
        if directory not in full_path.split("/"):
            full_path += ("/" + directory)

    return full_path

def merge_path_with_files(all_diffs: dict) -> list:
    """
    from a dict of dict[parent_path] = [files that differ]
    convert it to a list of (path, file1, file2)
    the path points only to the latest unpacked file
    so we must do some *magic* to include the full path.

    Ie apk files might have a path like IMAGES/system.img/app/system/Bluetooth/Bluetooth.apk
    and we have file1 = /tmp/.../.../Bluetooth.apk/META-INF/CERT.RSA
    So we want to merge the path and the file ending /META-INF/CERT.RSA into path
    """

    full_list = []
    for parent_path, disk_paths in all_diffs.items():
        for file_pair in disk_paths:
            file1 = file_pair.split(" ")[0]
            file2 = file_pair.split(" ")[1]

            full_path = get_full_path(parent_path, file1)
            full_list.append((full_path, file1, file2))


    return full_list

def get_target_dir_and_file_from_path(path: tuple) -> tuple:
    """
    Calculates the target_dir and target_file based upon the content of file_tuple
    format: path on index 0
            file1 on index 1
            file2 on index2
    returns target_dir, target_file
    """

    global OUTPUT_DIR

    last_slash = path.rfind("/")
    directory_part = path[:last_slash]
    file_part = path[last_slash + 1:]

    target_dir = f"{OUTPUT_DIR}/{directory_part}"
    target_file = f"{target_dir}/{file_part}.diff"

    return target_dir, target_file


# format on files: (path, file1, file2)
def create_block_summary(ext, files: list,) -> str:
    """
    Create one block of summary given the extension and it's files
    """
    summary = "================\n"
    summary += f"BEGIN {ext} files, {len(files)} found:\n"

    for file_pair in files:
        path = file_pair[0]
        file1 = file_pair[1]
        file2 = file_pair[2]

        summary += f"{path}\n"
        summary += f"\t{file1}\n"
        summary += f"\t{file2}\n\n"


    summary += f"END {ext} files\n"
    summary += f"================\n\n"
    return summary

def summary_for_uncomparable_files():
    """
    Some files may not be automatically compared
    Createa text summary presented to the user
    """
    global uncomparable_files
    summary = ""
    nr_uncomparable_files = len(uncomparable_files)
    if nr_uncomparable_files > 0:
        summary += f"{nr_uncomparable_files} files could not be automatically compared, these were:"
        summary += list_to_str(uncomparable_files)

    return summary



def summary_for_extensions(file_paths: list) -> dict:
    """
    create a dictionary of extensions and their occurance
    example dict[".json"] = 23 if there are 23 json files that differ
    file_paths format: (path, file1, file2)
    """

    file_extensions = {}
    ext_summary = {}

    for file_pair in file_paths:
        file1 = file_pair[1]
        ext = extension(file1)

        # some kernel files don't have any extension
        if ext == "":
            ext = "no-extension"

        if ext not in file_extensions:
            file_extensions[ext] = []
            ext_summary[ext] = 0

        ext_summary[ext] = ext_summary[ext] + 1
        file_extensions[ext].append(file_pair)


    return ext_summary, file_extensions


def create_summary(all_files: list, elapsed_time: float) -> str:
    """
    create a summary of the comparison and return as string
    """
    global uncomparable_files


    # Since we're preatty printing certificate difference of apk files
    # sometimes the CERT.RSA file will differ, but the output from apksigner
    # won't, therefore we make sure to ignore any diffs that turns out ot be empty
    diff_tree, nonempty_diffs = create_diff_tree(all_files)
    write_diff_tree(diff_tree)

    nr_different_files = len(nonempty_diffs)


    ext_summary, file_extensions = summary_for_extensions(nonempty_diffs)
    summary = ""

    for ext, files in file_extensions.items():
        summary += create_block_summary(ext, files)

    short_summary = "\n\n\n"
    short_summary += f"Comparison completed successfully in {elapsed_time} seconds\n"
    short_summary += f"In total there were {nr_different_files} files that differ\n"
    short_summary += f"There ending were: {ext_summary}\n"

    summary += short_summary
    summary += summary_for_uncomparable_files()

    # we rerturn the short summary so we can print it to screen directly
    return summary, short_summary



def filter_duplicates(files_to_filter: list) -> list:
    """
    Check to see if any files are duplicates of eachother
    return a list of only unique files that differ
    """
    unique_files1 = []
    unique_files2 = []
    unique_files_final = []

    for file_tuple in files_to_filter:
        file1 = file_tuple[1]
        file2 = file_tuple[2]

        # check if file exists alerady in unique_filtes
        # if it doesen't then its unique
        if not inside_unique_list(unique_files1, file1) and not inside_unique_list(unique_files2, file2):
            unique_files_final.append(file_tuple)
            unique_files1.append(file1)
            unique_files2.append(file2)

    return unique_files_final


def inside_unique_list(unique_files: list, path_to_compare: str) -> bool:
    """
    helper function for filter_duplicates()
    """
    for unique_file in unique_files:
        if files_are_equal(unique_file, path_to_compare):
            return True

    return False


def make_clean(target1: str, target2: str):
    """
    start comparison from a clean slate
    removes the files on disk for the corresponding target paths
    """
    global ROOT_COMPARISON
    run_shell_command(f"rm -rf {target1} {target2} {ROOT_COMPARISON}")




def extract(args, _):
    """
    Extract build date from a target file
    """
    zip_target = args.target_file

    if not file_exists(zip_target):
        print_error(f"opening {zip_target}: no such file")
        sys.exit(1)

    shell_props = [("BUILD_DATETIME", "ro.system.build.date.utc")]
    build_info = extract_build_info(args.target_file)

    for (prop, info) in build_info:
        for (_, sysprop) in shell_props:
            if sysprop == prop:
                print(f"{sysprop}={info}")


def extract_build_info(zip_target: str) -> str:
    """
    extracts build info from SYSTEM/build.prop given a target zip file
    """
    build_info = []
    props_to_extract = ["ro.system.build.date.utc"]

    with zipfile.ZipFile(zip_target, mode="r") as zfile:
        build_props = zfile.read("SYSTEM/build.prop").decode("utf-8").split("\n")

        for prop_info in build_props:
            if prop_info.startswith("#") or prop_info == "":
                continue
            prop, info = prop_info.split("=")
            if prop in props_to_extract:
                build_info.append((prop, info))

    return build_info


def compare(args, parser):
    """
    compare two target files
    store result in OUTPUT_DIR
    """
    global ZIP_FILENAME_1
    global ZIP_FILENAME_2
    global GRADLEW_PATH
    global QUIET
    global OUTPUT_DIR
    global all_commands

    OUTPUT_DIR = args.output[0]
    GRADLEW_PATH = args.gradlew_path[0]
    QUIET = args.quiet

    zip1_path = args.target1
    zip2_path = args.target2
    ZIP_FILENAME_1 = get_filename(zip1_path)
    ZIP_FILENAME_2 = get_filename(zip2_path)


    if not zip1_path.endswith(".zip") or not zip2_path.endswith(".zip"):
        print_error("both files must be zip files!")
        parser.print_help()
        sys.exit(1)



    start_time = time.time()
    all_diffs = compare_target_files(zip1_path, zip2_path, args.force_clean)
    elapsed_time = round(time.time() - start_time, 1)

    full_tuple_list = merge_path_with_files(all_diffs)
    final_diffs_list = []

    if args.no_filter_duplicates:
        final_diffs_list = full_tuple_list
    else:
        final_diffs_list = filter_duplicates(full_tuple_list)

    run_shell_command(f"rm -rf {OUTPUT_DIR}")
    full_summary, short_summary = create_summary(final_diffs_list, elapsed_time)



    print(short_summary)
    write_to_file(full_summary, "summary.txt")


def main():
    """
    set arguments and execute action
    """

    parser = argparse.ArgumentParser(
        description="Recursively unpack and compare two AOSP target files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        add_help=True)

    parser.add_argument("--version", action="version", version="%(prog)s 1.0")

    subparsers = parser.add_subparsers(title="actions", dest="actions")
    subparsers.required = True
    compare_parser = subparsers.add_parser("compare", help="compare two target files", add_help=True)

    compare_parser.add_argument("target1", help="path to the first target file")
    compare_parser.add_argument("target2", help="path to the second target file")
    compare_parser.add_argument("--force-clean",
                                help="Do not reuse previously unpacked target files",
                                action="store_true")

    compare_parser.add_argument("-q", "--quiet",
                                help="do not print all shell commands to stdout",
                                action="store_true")

    compare_parser.add_argument("--gradlew-path",
                                help="Path to the Android boot image editor tool (default ~/gradlew)",
                                nargs=1,
                                type=str,
                                default=["~/gradlew"])

    compare_parser.add_argument("--no-filter-duplicates",
                                help="Do no filter duplicate files during analysis",
                                action="store_true",
                                default=False)

    compare_parser.add_argument("-o", "--output",
                                help="output directory",
                                nargs=1,
                                default=["diffs"],
                                type=str)

    compare_parser.set_defaults(func=compare)

    extract_parser = subparsers.add_parser("extract",
                                           help="extract build date information from a target file",
                                           add_help=True,
                                           description="""Some metadata from an AOSP target file can be
                                           extracted by inspecting the SYSTEM/build.prop file.\n
                                           Returns the build date for the target file""")

    extract_parser.add_argument("target_file", help="from which target file to extract build info")


    extract_parser.set_defaults(func=extract)
    args = parser.parse_args()
    args.func(args, parser)


if __name__ == "__main__":
    main()
