@echo off
REM ============================================================
REM NEXUS - Generate a dev JWT token for API testing
REM Usage: generate_token.bat [role] [user_id]
REM        generate_token.bat analyst alice
REM ============================================================

SET ROLE=%1
SET USER=%2
IF "%ROLE%"=="" SET ROLE=analyst
IF "%USER%"=="" SET USER=dev-user

echo.
echo Generating JWT token for user=%USER% role=%ROLE%
echo.

cd /d "%~dp0.."
python -c "
from nexus.api.auth import create_token
token = create_token(user_id='%USER%', user_role='%ROLE%', department='IT', email='%USER%@nexus.local')
print('Token:')
print(token)
print()
print('Use in API calls:')
print('  Authorization: Bearer ' + token)
"
echo.
pause
