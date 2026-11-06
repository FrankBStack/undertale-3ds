// Host-only destination check. Never create a cache in the source game folder,
// including through an existing symlink/junction. Unresolvable paths fail closed.
#pragma once
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>

static bool texprep_roots_comparable(const wchar_t* left, const wchar_t* right) {
    bool leftUNC = wcslen(left) >= 8 && CompareStringOrdinal(left, 8, L"\\\\?\\UNC\\", 8, TRUE) == CSTR_EQUAL;
    bool rightUNC = wcslen(right) >= 8 && CompareStringOrdinal(right, 8, L"\\\\?\\UNC\\", 8, TRUE) == CSTR_EQUAL;
    if (leftUNC || rightUNC) {
        if (!leftUNC || !rightUNC) return false;
        const wchar_t* a = wcschr(left + 8, L'\\');
        const wchar_t* b = wcschr(right + 8, L'\\');
        if (!a || !b || a == left + 8 || b == right + 8 || !a[1] || !b[1]) return false;
        a = wcschr(a + 1, L'\\'); b = wcschr(b + 1, L'\\');
        int na = a ? (int) (a - left) : (int) wcslen(left);
        int nb = b ? (int) (b - right) : (int) wcslen(right);
        // Different share/server names can alias the same folder. Fail closed.
        return na == nb && CompareStringOrdinal(left, na, right, nb, TRUE) == CSTR_EQUAL;
    }
    // Two resolved local drive letters are comparable, including distinct drives.
    return wcslen(left) >= 6 && wcslen(right) >= 6 &&
        wcsncmp(left, L"\\\\?\\", 4) == 0 && wcsncmp(right, L"\\\\?\\", 4) == 0 &&
        ((left[4] >= L'A' && left[4] <= L'Z') || (left[4] >= L'a' && left[4] <= L'z')) &&
        ((right[4] >= L'A' && right[4] <= L'Z') || (right[4] >= L'a' && right[4] <= L'z')) &&
        left[5] == L':' && right[5] == L':' &&
        (!left[6] || left[6] == L'\\') && (!right[6] || right[6] == L'\\');
}

static bool texprep_output_safe_for(const char* input, const char* output, bool resolveFile) {
    if (!input || !*input || !output || !*output) return false;
    wchar_t source[4096], target[4096], canonicalSource[4096], canonicalTarget[4096];
    wchar_t* wideInput = texprep_wide(input);
    wchar_t* wideOutput = texprep_wide(output);
    DWORD a = wideInput ? GetFullPathNameW(wideInput, 4096, source, NULL) : 0;
    DWORD b = wideOutput ? GetFullPathNameW(wideOutput, 4096, target, NULL) : 0;
    free(wideInput); free(wideOutput);
    if (!a || a >= 4096 || !b || b >= 4096) return false;
    // The standalone packer's directory creation does not support extended outputs.
    if (wcsncmp(target, L"\\\\?\\", 4) == 0) return false;
    if (!resolveFile) {
        wchar_t* parent = wcsrchr(source, L'\\');
        if (!parent) return false;
        parent[1] = L'\0';
    }
    // Open the FILE first: its final target can be outside its lexical parent.
    HANDLE handle = CreateFileW(source, 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                               NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (handle == INVALID_HANDLE_VALUE) return false;
    a = GetFinalPathNameByHandleW(handle, canonicalSource, 4096, FILE_NAME_NORMALIZED);
    CloseHandle(handle);
    if (!a || a >= 4096) return false;
    wchar_t* slash;
    if (resolveFile) {
        slash = wcsrchr(canonicalSource, L'\\');
        if (!slash) return false;
        *slash = L'\0';
    }
    size_t length = wcslen(canonicalSource);
    while (length && canonicalSource[length - 1] == L'\\') canonicalSource[--length] = L'\0';
    slash = wcsrchr(canonicalSource, L'\\');
    if (slash && wcslen(slash + 1) == 16 && slash[8] >= L'1' && slash[8] <= L'5' &&
        CompareStringOrdinal(slash + 1, 7, L"chapter", 7, TRUE) == CSTR_EQUAL &&
        CompareStringOrdinal(slash + 9, 8, L"_windows", 8, TRUE) == CSTR_EQUAL) *slash = L'\0';
    a = (DWORD) wcslen(canonicalSource);
    // New output folders are allowed. Resolve their nearest existing parent.
    for (;;) {
        handle = CreateFileW(target, 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                            NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
        if (handle != INVALID_HANDLE_VALUE) break;
        DWORD error = GetLastError();
        if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) return false;
        slash = wcsrchr(target, L'\\');
        if (!slash || slash <= target + 2) return false;
        *slash = L'\0';
    }
    b = GetFinalPathNameByHandleW(handle, canonicalTarget, 4096, FILE_NAME_NORMALIZED);
    CloseHandle(handle);
    if (!b || b >= 4096) return false;
    if (!texprep_roots_comparable(canonicalSource, canonicalTarget)) return false;
    bool prefix = b >= a && CompareStringOrdinal(canonicalSource, (int) a, canonicalTarget, (int) a, TRUE) == CSTR_EQUAL;
    return !(prefix && (b == a || canonicalTarget[a] == L'\\'));
}
#else
#include <unistd.h>

static bool texprep_output_safe_for(const char* input, const char* output, bool resolveFile) {
    if (!input || !*input || !output || !*output) return false;
    char* visible = strdup(input);
    if (!visible) return false;
    char* slash = strrchr(visible, '/');
    if (!slash) { free(visible); visible = strdup("."); }
    else if (slash == visible) slash[1] = '\0';
    else *slash = '\0';
    char* source = resolveFile ? realpath(input, NULL) : (visible ? realpath(visible, NULL) : NULL);
    free(visible);
    if (!source) return false;
    if (resolveFile) {
        slash = strrchr(source, '/');
        if (!slash) { free(source); return false; }
        if (slash == source) slash[1] = '\0';
        else *slash = '\0';
    }
    slash = strrchr(source, '/');
    if (slash && strlen(slash + 1) == 16 && slash[8] >= '1' && slash[8] <= '5' &&
        strncmp(slash + 1, "chapter", 7) == 0 && strcmp(slash + 9, "_windows") == 0) {
        if (slash == source) slash[1] = '\0';
        else *slash = '\0';
    }
    char* target = strdup(output);
    if (!target) { free(source); return false; }
    char* resolved = NULL;
    for (;;) {
        resolved = realpath(target, NULL);
        if (resolved) break;
        slash = strrchr(target, '/');
        // Do not climb past an unresolved '..': a missing/symlinked prefix
        // cannot be normalized lexically without changing filesystem semantics.
        if ((slash && strcmp(slash + 1, "..") == 0) || strcmp(target, "..") == 0) break;
        if (!slash) { free(target); target = strdup("."); }
        else if (slash == target) slash[1] = '\0';
        else *slash = '\0';
        if (!target || strcmp(target, "/") == 0 || strcmp(target, ".") == 0) {
            if (target) resolved = realpath(target, NULL);
            break;
        }
    }
    size_t n = strlen(source);
    bool inside = resolved && strncmp(source, resolved, n) == 0 &&
                  (source[n - 1] == '/' || resolved[n] == '\0' || resolved[n] == '/');
    bool safe = resolved && !inside;
    free(source); free(target); free(resolved);
    return safe;
}
#endif

static bool texprep_output_safe(const char* input, const char* output) {
    // Neither the directory containing a link nor the final file's bundle is writable.
    return texprep_output_safe_for(input, output, false) && texprep_output_safe_for(input, output, true);
}
