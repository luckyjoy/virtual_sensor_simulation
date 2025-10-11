@echo off
setlocal
set REPORT_OUTPUT_DIR=allure-report
set REPORT_PORT=8000

echo.
echo ==========================================================
echo           Allure Report Generation with History
echo ==========================================================
echo.

rem --- 1. Cleanup and Preparation ---
rem Delete old results to ensure a fresh run.
IF EXIST allure-results rmdir /s /q allure-results >nul
echo Running pytest and collecting results into allure-results...
pytest --alluredir=allure-results
echo.

rem --- 2. Copy Environment Properties and Categories ---
echo Copying categories.json and environment.properties into the report directory...
rem Assuming 'supports' folder is in the project root.
copy supports\windows.properties allure-results\environment.properties >nul
copy supports\categories.json allure-results\ >nul
echo Environment files copied successfully.
echo.

rem --- 3. CRITICAL STEP: Copy previous report history for trending ---
IF EXIST "%REPORT_OUTPUT_DIR%\history" (
    echo Found previous history data. Copying to allure-results...
    xcopy "%REPORT_OUTPUT_DIR%\history" "allure-results\history\" /E /I /Q /Y >nul
    echo History copied from "%REPORT_OUTPUT_DIR%\history"
) ELSE (
    echo Previous report history folder not found at "%REPORT_OUTPUT_DIR%\history". Trend will start from this run.
)
echo.

rem --- 4. Generate Persistent Report (Enable Trend) ---
echo Generating Allure Report into persistent folder: %REPORT_OUTPUT_DIR%
rem The --clean flag ensures the folder is clean before merging data.
allure generate allure-results --clean -o %REPORT_OUTPUT_DIR%
echo.

rem --- 5. Start a local server and open the report ---
rem FINAL ATTEMPT: This uses the most standard Windows command `start` to launch the URL.
echo ======================================================================
echo  >> Starting a temporary web server to display the report... <<
echo.
echo  A new command window will open for the server process.
echo  To stop the server, simply CLOSE that new window.
echo ======================================================================

rem Change directory to the report folder to serve files from there.
pushd %REPORT_OUTPUT_DIR%

rem Start Python's built-in HTTP server in a new, non-blocking window.
start "Allure Report Server" python -m http.server %REPORT_PORT%

rem Give the server a generous moment to start up.
echo Waiting for server to initialize...
ping -n 6 127.0.0.1 >nul

rem Launch the browser to the local server URL using the most basic `start` command.
echo Opening report at http://localhost:%REPORT_PORT% ...
start http://localhost:%REPORT_PORT%

rem Return to the original directory
popd

echo.
echo Allure report generation and launch complete.
echo Report is permanently saved in the "%REPORT_OUTPUT_DIR%" folder.

endlocal

