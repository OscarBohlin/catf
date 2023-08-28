# compare AOSP target files - catf

A Python script for comparing two AOSP target files.


## Requirements

This was developed and tested using python version 3.8.10.

The scripts requires the [Android boot image editor](https://github.com/Android_boot_image_editor) program to compare `.img` files. Dowload [the zip fil](https://github.com/cfig/Android_boot_image_editor/releases) and unpack it, default path for this tool installation is in the home directory but it can be
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




# Example usage

Say you have two target files from different AOSP builds; `target1` and `target2`:

```bash
python3 aosp_target_files_diff.py compare target1 target2
```

It is also possible to extract the build information from a target file by:

```bash
python3 aosp_target_files_diff.py extract target1
```

Afterwards you see the result in the `summary.txt` file and under the `diffs` folder.

# Special thanks

This project would not have been possible by my employer [Tutus Data](https://tutus.se)! 




