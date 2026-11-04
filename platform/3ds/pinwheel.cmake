# The builder exports the same flag before preparing the event bindings.
option(CTRPORT_WEIRDSHD_PINWHEEL "Bounded pinwheel renderer (DR New only)" ON)
if("$ENV{CTRPORT_WEIRDSHD_PINWHEEL}" STREQUAL "0")
    set(CTRPORT_WEIRDSHD_PINWHEEL OFF)
elseif("$ENV{CTRPORT_WEIRDSHD_PINWHEEL}" STREQUAL "1")
    set(CTRPORT_WEIRDSHD_PINWHEEL ON)
endif()
if(NOT CTRPORT_AOT_MODULES)
    set(CTRPORT_WEIRDSHD_PINWHEEL OFF)
endif()
if(CTRPORT_WEIRDSHD_PINWHEEL AND CTRPORT_GAME STREQUAL "deltarune" AND CTRPORT_TARGET STREQUAL "n3ds")
    if(NOT "$ENV{CTRPORT_WEIRDSHD_PINWHEEL}" STREQUAL "1")
        message(FATAL_ERROR "Pinwheel event bindings need the matching builder flag; use build.sh")
    endif()
    set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/source/ctr_renderer.c" APPEND PROPERTY
        COMPILE_DEFINITIONS CTRPORT_WEIRDSHD_PINWHEEL)
    set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/source/ctr_renderer.c" APPEND PROPERTY
        OBJECT_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/source/ctr_pinwheel.inc;${CMAKE_CURRENT_SOURCE_DIR}/source/ctr_pinwheel_fast.inc")
endif()
