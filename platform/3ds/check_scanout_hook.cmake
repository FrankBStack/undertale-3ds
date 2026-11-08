# scanout (UNDERTALE): __wrap_CtrTextures_releaseMirrors (ctr_renderer.c's end) moves the game between the screens
# only when it was called from screensConfigureKeepBottom, which it tells by the return address alone: within
# SCANOUT_KEEP_CALL_WITHIN bytes of keepBottom's start. That holds only while the compiled code agrees, so this
# post-link check proves it on every UNDERTALE link and deletes the ELF otherwise (c26rev6 R428-1):
#   1. one screensConfigureKeepBottom and one __wrap_CtrTextures_releaseMirrors;
#   2. keepBottom is at least SCANOUT_KEEP_CALL_WITHIN bytes long, so no other function's call can fall in the window;
#   3. keepBottom calls the wrapper exactly CALLS times (-O2 copies its one source call into each branch), each a bl
#      whose return address is inside the window; no other reference to the wrapper or to the real releaseMirrors.
# A displaced or missing call would silently leave the Game screen change on screensMoveGame (or, with a short
# keepBottom, let a foreign caller in), so the build stops instead.
#   cmake -DELF=... -DNM=...-nm -DOBJDUMP=...-objdump -DSOURCE=.../ctr_renderer.c -DCALLS=3 -P check_scanout_hook.cmake
foreach(var ELF NM OBJDUMP SOURCE CALLS)
    if(NOT DEFINED ${var})
        message(FATAL_ERROR "check_scanout_hook.cmake: -D${var}= is required")
    endif()
endforeach()

function(scanout_fail why)
    file(REMOVE "${ELF}")
    message(FATAL_ERROR "scanout hook check: ${why}. ${ELF} deleted: the Game screen change's return-address window "
                        "(SCANOUT_KEEP_CALL_WITHIN, ctr_renderer.c) no longer matches the compiled keepBottom; see "
                        "tools/analysis/test_scanout_move.py.")
endfunction()

file(STRINGS "${SOURCE}" define REGEX "^#define SCANOUT_KEEP_CALL_WITHIN 0x[0-9a-fA-F]+u")
list(LENGTH define defines)
if(NOT defines EQUAL 1)
    scanout_fail("${defines} SCANOUT_KEEP_CALL_WITHIN definitions in ${SOURCE} (expected 1)")
endif()
string(REGEX MATCH "0x[0-9a-fA-F]+" within "${define}")
math(EXPR within "${within}")

execute_process(COMMAND "${NM}" -S --defined-only "${ELF}" OUTPUT_VARIABLE symbols RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
    scanout_fail("could not read the symbols")
endif()
string(REPLACE "\r" "" symbols "${symbols}")
foreach(name screensConfigureKeepBottom __wrap_CtrTextures_releaseMirrors)
    string(REGEX MATCHALL "[0-9a-f]+ [0-9a-f]+ [tT] ${name}\n" found "${symbols}")
    list(LENGTH found n)
    if(NOT n EQUAL 1)
        scanout_fail("${n} ${name} symbols (expected 1)")
    endif()
endforeach()
string(REGEX MATCH "([0-9a-f]+) ([0-9a-f]+) [tT] screensConfigureKeepBottom\n" m "${symbols}")
math(EXPR keep "0x${CMAKE_MATCH_1}")
math(EXPR size "0x${CMAKE_MATCH_2}")
math(EXPR keep_end "${keep} + ${size}" OUTPUT_FORMAT HEXADECIMAL)
math(EXPR keep_hex "${keep}" OUTPUT_FORMAT HEXADECIMAL)
if(size LESS within)
    scanout_fail("keepBottom is ${size} B, shorter than the ${within} B window")
endif()

execute_process(COMMAND "${OBJDUMP}" -d --no-show-raw-insn "--start-address=${keep_hex}" "--stop-address=${keep_end}" "${ELF}"
                OUTPUT_VARIABLE text RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
    scanout_fail("objdump failed on keepBottom")
endif()
string(REPLACE ";" "@" text "${text}")
string(REPLACE "\r" "" text "${text}")
string(REPLACE "\n" ";" lines "${text}")
set(sites "")
set(count 0)
foreach(line IN LISTS lines)
    if(line MATCHES "<(__wrap_|__real_)?CtrTextures_releaseMirrors(\\+0x[0-9a-f]+)?>")
        if(NOT line MATCHES "^ *([0-9a-f]+):[ \t]+bl[ \t]+[0-9a-f]+ <__wrap_CtrTextures_releaseMirrors>")
            string(STRIP "${line}" line)
            scanout_fail("keepBottom refers to releaseMirrors other than by a bl to the wrapper: '${line}'")
        endif()
        math(EXPR after "0x${CMAKE_MATCH_1} + 4 - ${keep}")
        math(EXPR at "0x${CMAKE_MATCH_1} - ${keep}" OUTPUT_FORMAT HEXADECIMAL)
        if(after GREATER_EQUAL within)
            scanout_fail("keepBottom's releaseMirrors call at +${at} returns outside the ${within} B window")
        endif()
        list(APPEND sites "+${at}")
        math(EXPR count "${count} + 1")
    endif()
endforeach()
if(NOT count EQUAL CALLS)
    scanout_fail("keepBottom calls releaseMirrors ${count} times (${sites}), expected ${CALLS}")
endif()
message(STATUS "scanout hook check: keepBottom (${size} B) calls releaseMirrors at ${sites}, all within ${within} B")
