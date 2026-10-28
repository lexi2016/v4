#!/bin/sh
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH LC_ALL=C
[ "$#" -eq 0 ] || exit 2
[ "$(/usr/bin/id -u)" = 0 ] || { echo ROOT_REQUIRED >&2; exit 2; }
[ "$(/bin/date +%s)" -le 1793199600 ] || { echo REQUEST_EXPIRED >&2; exit 2; }
[ "$(/usr/bin/shasum -a 256 /bin/sleep | /usr/bin/awk '{print $1}')" = c30e72b2e2d6a4eb32b6f38f07815346bc734d031d3c712d9123f28d8b237051 ] || exit 2
/usr/bin/codesign -v -R='anchor apple' /bin/sleep
echo NO_ACTIVE_COORDINATOR_REVIEW_EXAMPLE_ONLY >&2
exit 2
[ "$(/bin/ps -ww -p 93640 -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}')" = be723bfca787f4203c1f45f0fcbd66c0298ed0ce052247f44ad5051182ca06bd ] || { echo MAIN_PID_DRIFT >&2; exit 2; }
[ "$(/bin/launchctl print gui/501/com.lexi.v35.scheduler | /usr/bin/awk '$1 == "pid" && $2 == "=" {print $3}')" = 93640 ] || exit 2
[ "$(/usr/bin/shasum -a 256 /Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist | /usr/bin/awk '{print $1}')" = a75e04276cd243ecdb3ee59b3effe35e7a8ec6fa4cc9d670304c0bd3c3811292 ] || exit 2
[ "$(/bin/ps -ww -p 93643 -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}')" = bb8a094b267595d71b7d2344fc44fc165f6b0a0f60555d812ea56c999d4832fe ] || { echo API_PID_DRIFT >&2; exit 2; }
[ "$(/bin/launchctl print gui/501/com.lexi.v35.api-only | /usr/bin/awk '$1 == "pid" && $2 == "=" {print $3}')" = 93643 ] || exit 2
[ "$(/usr/bin/shasum -a 256 /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist | /usr/bin/awk '{print $1}')" = 261cd6ea1453448cecf6b0254b37e599214d20427ffd238042bcdfa75232403e ] || exit 2
umask 022
/bin/mkdir -m 755 /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a || { echo EXISTING_INTENT_NO_RETRY >&2; exit 2; }
printf '%s\n' d2599dab3857237bf4ea8de535be31599bbff528dbeccd509cc5c1ebeb56c8a0 > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/plan_sha256
printf '%s\n' INTENT > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/main.intent
set +e
/bin/launchctl debug gui/501/com.lexi.v35.scheduler --program /bin/sleep -- 604800 > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/main.stdout 2> /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/main.stderr
result=$?
set -e
printf '%s\n' "$result" > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/main.rc
[ "$result" -eq 0 ] || { echo DEBUG_FAILED_NO_RETRY >&2; exit "$result"; }
printf '%s\n' INTENT > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/api.intent
set +e
/bin/launchctl debug gui/501/com.lexi.v35.api-only --program /bin/sleep -- 604800 > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/api.stdout 2> /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/api.stderr
result=$?
set -e
printf '%s\n' "$result" > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/api.rc
[ "$result" -eq 0 ] || { echo DEBUG_FAILED_NO_RETRY >&2; exit "$result"; }
printf '%s\n' COMPLETE > /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a/COMPLETE
printf '%s\n' /private/var/tmp/v4-r7-nextspawn-9b686013aba041dda454232cf24fb85a
