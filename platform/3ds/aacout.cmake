# AAC retirement (UNDERTALE only). Insert reusable input regions at the original
# vendor boundary inside the existing output sections, retaining their extents.
# Inputs deliberately start with .aacout, not .text/.rodata: earlier wildcards
# must not consume them. The ordinary late_reserve.ld remains unchanged.
set(aacout_toolchain_ld "${CTRPORT_DKA_BIN}/../arm-none-eabi/lib/3dsx.ld")
file(READ "${aacout_toolchain_ld}" aacout_ld)
foreach(kind text rodata)
    set(aacout_prefix "")
    if(kind STREQUAL "text")
        # GCC's startup object precedes the application objects in .text.*.
        set(aacout_prefix "        *crtbegin.o(.text.*)\n")
    endif()
    foreach(source IN LISTS PLATFORM_SOURCES ENGINE_SOURCES VENDOR_SOURCES)
        # CMake hashes source directories when an object path would be too long.
        # Only the filename survives; the pre-link check requires exactly one
        # matching linker input, including when two sources share a basename.
        get_filename_component(aacout_object "${source}" NAME)
        string(REGEX REPLACE "\\.[cCSs]$" ".o" aacout_object "${aacout_object}")
        if(kind STREQUAL "text")
            if(aacout_object STREQUAL "ctr_audio_decoder.o")
                # The retired shared wrapper has no caller; retain its padding.
                string(APPEND aacout_prefix "        /* aacout object */ KEEP(*/${aacout_object}(.text.*))\n")
            else()
                string(APPEND aacout_prefix "        /* aacout object */ */${aacout_object}(.text.*)\n")
            endif()
        else()
            string(APPEND aacout_prefix "        /* aacout object */ */${aacout_object}(.rodata)\n")
        endif()
    endforeach()
    if(kind STREQUAL "text")
        set(aacout_capacity 43396)
        set(aacout_match "*(.text.*)")
    else()
        # 23,530 B vendor payload, plus its original 2 B internal alignment.
        set(aacout_capacity 23532)
        set(aacout_match "*(.rodata)")
    endif()
    set(aacout_region "${aacout_prefix}
        . = ALIGN(4);
        __aacout_${kind}_start = ABSOLUTE(.);
        KEEP(*(.aacout.${kind} .aacout.${kind}.*))
        __aacout_${kind}_used_end = ABSOLUTE(.);
        ASSERT(__aacout_${kind}_used_end <= __aacout_${kind}_start + ${aacout_capacity}, \"AAC ${kind} slot overflow\");
        . += __aacout_${kind}_used_end <= __aacout_${kind}_start + ${aacout_capacity} ? __aacout_${kind}_start + ${aacout_capacity} - __aacout_${kind}_used_end : 0;
        __aacout_${kind}_end = ABSOLUTE(.);
        ${aacout_match}")
    string(FIND "${aacout_ld}" "${aacout_match}" aacout_found)
    if(aacout_found LESS 0)
        message(FATAL_ERROR "aacout: unsupported toolchain linker script; missing ${aacout_match}")
    endif()
    string(REPLACE "${aacout_match}" "${aacout_region}" aacout_ld "${aacout_ld}")
endforeach()
set(aacout_output "${CMAKE_CURRENT_BINARY_DIR}/aacout.ld")
file(WRITE "${aacout_output}.new" "${aacout_ld}")
configure_file("${aacout_output}.new" "${aacout_output}" COPYONLY)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${aacout_toolchain_ld}" "${CMAKE_CURRENT_LIST_FILE}")
set_property(TARGET ctrport APPEND PROPERTY LINK_DEPENDS "${aacout_output}")
string(REPLACE "-T 3dsx.ld%s" "-T aacout.ld" CTRPORT_SPECS_NEW "${CTRPORT_SPECS_NEW}")

# Remove AAC in every UT configuration. Select padding after Tremor discovery;
# only Release/RelWithDebInfo with Tremor have the reviewed decoder extents.
set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/source/ctr_audio_decoder.c"
    APPEND PROPERTY COMPILE_DEFINITIONS CTRPORT_NO_AAC)
function(aacout_configure_decoder)
    string(TOUPPER "${CMAKE_BUILD_TYPE}" aacout_build_type)
    if(NOT aacout_build_type MATCHES "^(DEBUG|RELEASE|RELWITHDEBINFO|MINSIZEREL)$")
        message(FATAL_ERROR "aacout: unsupported build type '${CMAKE_BUILD_TYPE}'; expected Debug, Release, RelWithDebInfo or MinSizeRel")
    endif()
    set(aacout_mode "")
    if((aacout_build_type STREQUAL "RELEASE" OR aacout_build_type STREQUAL "RELWITHDEBINFO")
       AND CTRPORT_USE_TREMOR AND TREMOR_INCLUDE_DIR AND TREMOR_LIBRARY AND OGG_LIBRARY)
        set(aacout_mode "--aacout-pad")
    endif()
    get_target_property(aacout_delegate ctrport C_COMPILER_LAUNCHER)
    set_property(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER
        "${CTRPORT_PYTHON_EXECUTABLE};-X;utf8;-I;${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../../tools/buildcache/aacout_compile.py;${aacout_mode};${aacout_delegate};--aacout-compiler")
endfunction()
set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/source/ctr_audio_decoder.c"
    APPEND PROPERTY OBJECT_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/buildcache/aacout_compile.py")

# Check the actual linker argv/response files before invoking GCC. This launch
# property supports CMake 3.19; C_LINKER_LAUNCHER requires CMake 3.21.
set_property(TARGET ctrport PROPERTY RULE_LAUNCH_LINK
    "\"${CTRPORT_PYTHON_EXECUTABLE}\" -X utf8 -I \"${CMAKE_CURRENT_SOURCE_DIR}/../../tools/buildcache/aacout_compile.py\" --aacout-link \"${aacout_output}\" --")
set_property(TARGET ctrport APPEND PROPERTY LINK_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/buildcache/aacout_compile.py")
