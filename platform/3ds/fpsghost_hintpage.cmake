if(CTRPORT_GAME STREQUAL "undertale")
    target_sources(ctrport PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/source/z_fpsghost_hintpage.c")
    set_source_files_properties("${CMAKE_CURRENT_SOURCE_DIR}/source/z_fpsghost_hintpage.c"
        PROPERTIES COMPILE_OPTIONS "-Os;-fno-merge-constants")
endif()
