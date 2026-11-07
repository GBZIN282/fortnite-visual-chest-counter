/*
 * Fortnite Visual Chest Counter - launcher ("Fortnite Visual Chest Counter.exe").
 *
 * Its only job: start the desktop app with the official, signed python.org runtime shipped next to it,
 *
 *     runtime\python\pythonw.exe -m fortnite_chest_counter.gui [the arguments given to this program]
 *
 * in the program folder, and exit. No network, no registry, no files written, no elevation.
 * If the runtime is missing (usually: started from inside the zip), it says so in a message box.
 *
 * Built by packaging/build_release.py:  windres (icon, version info, manifest) + gcc -O2 -s -mwindows.
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

#define APP_NAME L"Fortnite Visual Chest Counter"
#define LONG_PATH 32768

static wchar_t folder[LONG_PATH], python[LONG_PATH], command[LONG_PATH + 1024];

static void fail(const wchar_t *text)
{
    MessageBoxW(NULL, text, APP_NAME, MB_OK | MB_ICONERROR);
}

/* The command line after the program name (same splitting rule as CommandLineToArgvW for argv[0]). */
static const wchar_t *arguments(const wchar_t *line)
{
    int quoted = 0;
    while (*line && (quoted || (*line != L' ' && *line != L'\t'))) {
        if (*line == L'"')
            quoted = !quoted;
        line++;
    }
    while (*line == L' ' || *line == L'\t')
        line++;
    return line;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR ignored, int show)
{
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    const wchar_t *args;
    wchar_t message[600];
    wchar_t *slash;
    DWORD length;

    (void)instance; (void)previous; (void)ignored; (void)show;

    length = GetModuleFileNameW(NULL, folder, LONG_PATH);
    if (length == 0 || length >= LONG_PATH) {
        fail(L"Could not find the program folder.");
        return 1;
    }
    slash = wcsrchr(folder, L'\\');
    if (slash)
        *slash = L'\0';

    if (wcslen(folder) + 40 >= LONG_PATH) {
        fail(L"The program folder path is too long. Move the folder somewhere shorter, for example your Desktop.");
        return 1;
    }
    wcscpy(python, folder);
    wcscat(python, L"\\runtime\\python\\pythonw.exe");
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        fail(L"The program files were not found next to this file.\n\n"
             L"Please extract the WHOLE zip file first (right-click the zip, \"Extract All\"), then open "
             APP_NAME L" from the extracted folder.");
        return 1;
    }

    args = arguments(GetCommandLineW());
    if (wcslen(python) + wcslen(args) + 64 >= LONG_PATH + 1024) {
        fail(L"The command line is too long.");
        return 1;
    }
    wcscpy(command, L"\"");
    wcscat(command, python);
    wcscat(command, L"\" -m fortnite_chest_counter.gui");
    if (*args) {
        wcscat(command, L" ");
        wcscat(command, args);
    }

    ZeroMemory(&startup, sizeof startup);
    startup.cb = sizeof startup;
    ZeroMemory(&process, sizeof process);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, 0, NULL, folder, &startup, &process)) {
        _snwprintf(message, 599, L"The app could not be started (Windows error %lu).\n\n"
                                 L"Extract the whole zip again and keep every file and folder together.",
                   (unsigned long)GetLastError());
        message[599] = L'\0';
        fail(message);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
