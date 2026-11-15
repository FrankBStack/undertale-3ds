# gofps (change hiscase, 11-15): the move back up's page copy leaves the counter on its screen (z_gofps.c). UNDERTALE only.
if(CTRPORT_GAME STREQUAL "undertale")
    target_sources(ctrport PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/source/z_gofps.c")
    set_source_files_properties("${CMAKE_CURRENT_SOURCE_DIR}/source/z_gofps.c" PROPERTIES COMPILE_OPTIONS "-Os")
endif()
