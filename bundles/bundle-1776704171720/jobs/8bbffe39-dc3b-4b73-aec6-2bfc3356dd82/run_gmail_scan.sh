#!/bin/bash
set -euo pipefail

OAUTH_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
USER_EMAIL='cbadcock@gmail.com'
API='https://gmail.googleapis.com/gmail/v1/users/me'
QUERY='in:inbox category:personal newer_than:4d -category:promotions -category:social'
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

sqlq(){ printf "%s" "$1" | perl -pe "s/'/''/g"; }
iso_from_ms(){ local ms="$1"; local sec=$((ms/1000)); date -u -r "$sec" '+%Y-%m-%dT%H:%M:%SZ'; }
clean_space(){ printf "%s" "$1" | tr '\n' ' ' | perl -CS -pe 's/\s+/ /g; s/^\s+|\s+$//g'; }
lower(){ printf "%s" "$1" | tr '[:upper:]' '[:lower:]'; }

ACCESS_TOKEN="$(sqlite3 "$OAUTH_DB" "select access_token from oauth_tokens where connection_id='google:personal' limit 1;")"
LIST_JSON="$TMPDIR/list.json"
curl -sS -G -H "Authorization: Bearer $ACCESS_TOKEN" --data-urlencode "q=$QUERY" --data-urlencode "maxResults=100" "$API/messages" > "$LIST_JSON"
if jq -e '.error' "$LIST_JSON" >/dev/null; then echo "gmail api error: $(jq -r '.error.message' "$LIST_JSON")"; exit 1; fi

THREADS_FILE="$TMPDIR/threads.txt"
jq -r '.messages[]?.threadId' "$LIST_JSON" | awk 'NF && !seen[$0]++' > "$THREADS_FILE"
SCANNED_COUNT=$(grep -c . "$THREADS_FILE" || true)
: > "$TMPDIR/candidates.tsv"
: > "$TMPDIR/skips.log"

while IFS= read -r THREAD_ID; do
  [ -n "$THREAD_ID" ] || continue
  THREAD_JSON="$TMPDIR/$THREAD_ID.json"
  curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" "$API/threads/$THREAD_ID?format=full" > "$THREAD_JSON"
  if jq -e '.error' "$THREAD_JSON" >/dev/null; then echo "api_error" >> "$TMPDIR/skips.log"; continue; fi
  MSG_COUNT=$(jq '.messages|length' "$THREAD_JSON")
  [ "$MSG_COUNT" -gt 0 ] || { echo "empty_thread" >> "$TMPDIR/skips.log"; continue; }
  LAST_JSON="$TMPDIR/${THREAD_ID}_last.json"
  jq 'def h($n): ([.payload.headers[]? | select((.name|ascii_downcase)==($n|ascii_downcase)) | .value][0] // ""); .messages | sort_by(.internalDate|tonumber) | last | {id,threadId,internalDate,from:h("From"),subject:h("Subject"),date:h("Date"),snippet,labels:(.labelIds // [])}' "$THREAD_JSON" > "$LAST_JSON"
  LAST_FROM=$(jq -r '.from' "$LAST_JSON")
  LAST_SUBJECT=$(jq -r '.subject' "$LAST_JSON")
  LAST_SNIPPET=$(jq -r '.snippet // ""' "$LAST_JSON")
  LAST_MSG_ID=$(jq -r '.id' "$LAST_JSON")
  LAST_MS=$(jq -r '.internalDate|tonumber' "$LAST_JSON")
  EMAIL_DATE=$(iso_from_ms "$LAST_MS")
  LAST_TEXT=$(clean_space "$LAST_SUBJECT $LAST_SNIPPET")
  LAST_LC=$(lower "$LAST_TEXT")
  LAST_FROM_LC=$(lower "$LAST_FROM")
  if printf "%s" "$LAST_FROM_LC" | grep -q "$USER_EMAIL"; then echo "resolved_by_user_reply" >> "$TMPDIR/skips.log"; continue; fi
  THREAD_TEXT=$(jq -r 'def h($n): ([.payload.headers[]? | select((.name|ascii_downcase)==($n|ascii_downcase)) | .value][0] // ""); .messages | sort_by(.internalDate|tonumber) | .[] | ((h("Subject") + " " + (.snippet // "")) | ascii_downcase)' "$THREAD_JSON" | tr '\n' ' ')
  if printf "%s" "$LAST_LC $THREAD_TEXT" | grep -Eqi '(^|[^a-z])(confirmed|extension filed|filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks[, ]+got it|thank you[, ]+got it|will provide (an )?update|keep an eye out|we (were not|weren.t) able to locate it)($|[^a-z])'; then echo "resolved_or_status_only" >> "$TMPDIR/skips.log"; continue; fi
  if printf "%s" "$LAST_LC" | grep -Eqi '(automatic reply|auto reply|out of office|vacation responder|delivery status|read receipt)'; then echo "auto_reply_or_system" >> "$TMPDIR/skips.log"; continue; fi
  if printf "%s" "$LAST_LC" | grep -Eqi '(newsletter|unsubscribe|sale|discount|promo|marketing|receipt|order (confirmed|shipped)|tracking number|security alert|sign in from a new device|verification code|one-time passcode|otp|bill is ready|statement is available|view online)'; then echo "notification_or_marketing" >> "$TMPDIR/skips.log"; continue; fi
  if printf "%s" "$LAST_LC" | grep -Eqi '(invitation for telehealth appointment|join zoom meeting|calendar invitation|updated invitation|event updated)' && ! printf "%s" "$LAST_LC" | grep -Eqi '(confirm|please respond|complete|fill out|submit|forms|paperwork|check-?in|echeck|verify|action required)'; then echo "calendar_or_informational" >> "$TMPDIR/skips.log"; continue; fi
  if ! printf "%s" "$LAST_LC" | grep -Eqi '(please|can you|could you|reply|respond|review|sign|complete|fill out|submit|upload|pay|payment due|invoice|bill due|confirm|verify|send|provide|need you to|action required|required|secure message|questionnaire|consent form|document request|follow up|next steps|attention needed|due )'; then echo "no_clear_action" >> "$TMPDIR/skips.log"; continue; fi
  SENDER_NAME=$(printf "%s" "$LAST_FROM" | sed -E 's/<[^>]+>//; s/"//g; s/^[[:space:]]+//; s/[[:space:]]+$//')
  SENDER_EMAIL=$(printf "%s" "$LAST_FROM" | sed -nE 's/.*<([^>]+)>.*/\1/p')
  ORG="$SENDER_NAME"; [ -n "$ORG" ] || ORG="$SENDER_EMAIL"; ORG=$(clean_space "$ORG")
  TITLE=''; KIND='general'; FIN_SCORE=0; PRIORITY=2
  if printf "%s" "$LAST_LC" | grep -Eqi '(payment due|invoice|amount due|past due|overdraft|negative balance|low balance|bill due|make a payment)'; then TITLE="Make a payment: $ORG"; KIND='finance'; PRIORITY=1; if printf "%s" "$LAST_LC" | grep -Eqi '(overdraft|negative balance|past due|final notice)'; then FIN_SCORE=3; else FIN_SCORE=2; fi
  elif printf "%s" "$LAST_LC" | grep -Eqi '(court|case|legal|orders filed|filing|hearing|motion|petition)'; then TITLE="Review legal filing: $ORG"; PRIORITY=1
  elif printf "%s" "$LAST_LC" | grep -Eqi '(telehealth|appointment|confirm appointment|please confirm|check-?in|echeck|paperwork)'; then TITLE="Confirm appointment: $ORG"
  elif printf "%s" "$LAST_LC" | grep -Eqi '(secure message|please reply|reply requested|respond|response needed)'; then TITLE="Respond to message: $ORG"
  elif printf "%s" "$LAST_LC" | grep -Eqi '(questionnaire|application|consent form|fill out|submit form|registration form|waiver)'; then TITLE="Submit form: $ORG"
  elif printf "%s" "$LAST_LC" | grep -Eqi '(upload|attach|required document|document request|send us.*document|proof of|id card)'; then TITLE="Upload document: $ORG"
  elif printf "%s" "$LAST_LC" | grep -Eqi '(document attached|please review|review document|forms attached|notice attached)'; then TITLE="Review document: $ORG"
  elif printf "%s" "$LAST_LC" | grep -Eqi '(send|provide|need.*information|share.*information)'; then TITLE="Send information: $ORG"
  elif printf "%s" "$LAST_LC" | grep -Eqi '(follow up|next steps|reminder)'; then TITLE="Follow up with: $ORG"
  else TITLE="Respond to message: $ORG"; fi
  TITLE=$(clean_space "$TITLE")
  TITLE=$(printf "%s" "$TITLE" | sed -E 's/^(Reply:|RE:|Fwd:|Hello Corey,|Invitation for[[:space:]]+)//I')
  DESC=$(clean_space "$LAST_SNIPPET"); if [ -z "$DESC" ]; then DESC=$(clean_space "$LAST_SUBJECT"); fi; [ ${#DESC} -gt 280 ] && DESC="${DESC:0:277}..."
  SOURCE_JSON=$(jq -nc --arg subject "$LAST_SUBJECT" --arg from "$LAST_FROM" --arg email_date "$EMAIL_DATE" --arg thread_id "$THREAD_ID" '{subject:$subject,from:$from,email_date:$email_date,thread_id:$thread_id}')
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$THREAD_ID" "$LAST_MSG_ID" "$LAST_FROM" "$EMAIL_DATE" "$ORG" "$TITLE" "$DESC" "$PRIORITY" "$KIND" "$FIN_SCORE|$SOURCE_JSON" >> "$TMPDIR/candidates.tsv"
done < "$THREADS_FILE"

FINAL="$TMPDIR/final.tsv"
awk -F '\t' 'function splitmeta(s,a){return split(s,a,"|")} {splitmeta($10,m); score=m[1]+0; day=substr($4,1,10); key=tolower($3) "|" day; if ($9=="finance") {if (!(key in best) || score > bestScore[key]) {best[key]=$0; bestScore[key]=score}} else {print $0}} END {for (k in best) print best[k]}' "$TMPDIR/candidates.tsv" > "$FINAL"

INSERTED=0
while IFS=$'\t' read -r THREAD_ID MSG_ID FROM EMAIL_DATE ORG TITLE DESC PRIORITY KIND META; do
  [ -n "$MSG_ID" ] || continue
  SOURCE_JSON="${META#*|}"
  DUP_COUNT=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where source='gmail' and status='open' and (gmail_message_id='$(sqlq "$MSG_ID")' or json_extract(source_details,'$.thread_id')='$(sqlq "$THREAD_ID")' or (created_at >= datetime('now','-14 days') and lower(coalesce(json_extract(source_details,'$.from'),'')) = lower('$(sqlq "$FROM")') and lower(title)=lower('$(sqlq "$TITLE")')));")
  if [ "$DUP_COUNT" -gt 0 ]; then echo "duplicate_existing_task" >> "$TMPDIR/skips.log"; continue; fi
  sqlite3 "$ADMIN_DB" "insert into tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details, created_at, updated_at) values ('$(sqlq "$TITLE")','$(sqlq "$DESC")',NULL,$PRIORITY,'open','gmail','$(sqlq "$MSG_ID")','$(sqlq "$SOURCE_JSON")',datetime('now'),datetime('now'));"
  INSERTED=$((INSERTED+1))
done < "$FINAL"

SKIP_SUMMARY=$(sort "$TMPDIR/skips.log" | uniq -c | awk '{printf "%s%s:%s", sep, $2, $1; sep=", "}')
[ -n "$SKIP_SUMMARY" ] || SKIP_SUMMARY='none'
echo "scanned count: $SCANNED_COUNT"
echo "inserted count: $INSERTED"
echo "skipped reasons: $SKIP_SUMMARY"
