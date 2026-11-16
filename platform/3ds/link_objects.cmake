# Writes OUT (release-link.objects): the sha256 of the linked ELF, of its map, and of each plain object file the link
# loaded (the map's LOAD lines with a path relative to the build directory DIR, ending in .o). check_devonly_aac.py
# --release-objdir reads input section alignments from those objects and accepts one only when its file has the sha256
# recorded here for this ELF and map (c26rev8 BS13-1: a stale or other build's objects are refused). Never fails the
# build: an object it cannot hash is left out, and the proof refuses that object.
file(SHA256 "${ELF}" elf_sha)
file(SHA256 "${MAP}" map_sha)
file(STRINGS "${MAP}" loads REGEX "^LOAD ")
set(out "# release-link.objects (link_objects.cmake): sha256 of this link's ELF, map and plain object inputs\n")
string(APPEND out "elf ${elf_sha}\nmap ${map_sha}\n")
set(seen "")
foreach(line IN LISTS loads)
    string(REGEX REPLACE "^LOAD " "" path "${line}")
    if(IS_ABSOLUTE "${path}" OR NOT path MATCHES "\\.o$" OR path MATCHES "[ \t]")
        continue()
    endif()
    if(path IN_LIST seen OR NOT EXISTS "${DIR}/${path}")
        continue()
    endif()
    list(APPEND seen "${path}")
    file(SHA256 "${DIR}/${path}" sha)
    string(APPEND out "${sha} ${path}\n")
endforeach()
file(WRITE "${OUT}.new" "${out}")
file(RENAME "${OUT}.new" "${OUT}")
