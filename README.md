# compare AOSP target files - catf

A Python script for comparing two AOSP target files.

## Requirements

This was developed and tested using python version 3.8.10 and on Ubuntu 22.04.

The scripts requires the [Android boot image editor](https://github.com/Android_boot_image_editor) program to compare `.img` files. Dowload [the zip fil](https://github.com/cfig/Android_boot_image_editor/releases) and unpack it, default path for this tool installation is in the users home directory but it can be
specified to elsewhere. Cloning its repository will not work for computers without internet access since it needs
to download certain gradle dependencies on first run.

Following packages are required by the script and Andoird boot image editor on Ubuntu:

```bash
sudo apt install simg2img p7zip-full p7zip-git device-tree-compiler lz4 xz-utils zlib1g-
dev openjdk-17-jdk gcc g++ python3 python-is-python3 android-sdk-libsparse-utils
```

Also recommended is a tool called `vbindiff` that can highlight and show differences in binary files. It can be
installed with

```bash
sudo apt install vbindiff
```

# Why is this needed?

When AOSP is being compiled it includes metadata in the compiled binaries and config files. For an example the build process will include (among other things) the hostname and username of the machine as well as the current date and time. This means that two identical copies of the source code will generate different binary files.

For security reasons, we might want to verify that a compiled target file is compiled from the proclaimed source code and hasn't been altered. 

Today there is no widely used tool to compare these target files. We can unpack the files with `.zip` and run `diff -qrwBaN` which will yield hundreds of different binary files. Tools like `diffoscope` will be able to recursively compare two files and produce a neat summary. But it cannot compare and unpack Android image files resulting in massive binary diffs between large images.

These image files have to be handled differently since they're too big to manually compare. Some of these images are the boot image, userdata image, system image and so on. Some of these images are *Andoird sparse images* that can be extracted using `simg2img` and ``7z`` on a Linux machine, but far from all of them.

The bootloader and other images cannot be extracted using standardized tools because (among other thigns) the [bootloader configuration](https://source.android.com/docs/core/architecture/bootloader/boot-image-header) might change overtime, resulting in existing solutions no longer working.

**Clearly, we need a tool that can unpack these image files**

This is the job for the [Android boot image editor](https://github.com/Android_boot_image_editor) and is the reson it's an requirement for using this script.

`catf` uses this image editor to unpack and compare image files recursively and producing an easy to understand difference between two target files.


# What is a target file?
When you're compiling the Android Open Source Project, AOSP for short the resulting binaries are stored in a *target file* that can be flash onto a device.
[This](https://source.android.com/docs/setup/build/building) link will describe how to clone and build the defult AOSP that requires choosing the target branch and device.

The compilation is started with the `m` command and after it's finished you will have a compiled version of Android.

The building procedure for AOSP will take a **LOOOOOONG** time. If you are not running in professional hardware with at least 30 cores this will take several hours. In my experience 32 cores with 64GB of RAM compiled AOSP on approximately 1 hour. 

To locate the target file, run the following command from the project root directory:
```bash
find out -name "*-target_files-*.zip" -type f
```

# Example usage

Say you have two target files from different AOSP builds; `<target1>` and `<target2>`:

```bash
python3 aosp_target_files_diff.py compare <target1> <target2>
```

It is also possible to extract the build information from a target file by:

```bash
python3 aosp_target_files_diff.py extract <target1>
```
The script will print out any executed commands to standard out.

## Results
When the comparison is done, the results are stored in the `summary.txt` file and under the `diffs` folder.

The `summary.txt` file will categorize all files that differ with regards to file extensions.

The `diffs` folder is a representation of the compared target files. If the file `diffs/IMAGES/system.img/a.txt` exists, it is because the `a.txt` file differ between the target files, and is located under `IMAGES/system.img` (for an example).

# Special thanks

This project would not have been possible by my former employer [Tutus Data](https://tutus.se)! 




