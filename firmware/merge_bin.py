Import("env")


def merge_binaries(source, target, env):
    build_dir = env.subst("$BUILD_DIR")
    app_bin = str(target[0])
    merged_bin = app_bin.replace("firmware.bin", "firmware_merged.bin")

    # Usa esptool fornito da PlatformIO
    esptool = env.subst("$PYTHONEXE") + " " + env.subst(
        "$PROJECT_PACKAGES_DIR/tool-esptoolpy/esptool.py"
    )

    cmd = (
        f"{esptool} "
        f"--chip esp32 merge_bin "
        f"-o {merged_bin} "
        f"0x1000 {build_dir}/bootloader.bin "
        f"0x8000 {build_dir}/partitions.bin "
        f"0x10000 {app_bin}"
    )

    print(f"[MERGE] Creazione firmware merged: {merged_bin}")
    env.Execute(cmd)


env.AddPostAction("$BUILD_DIR/firmware.bin", merge_binaries)
