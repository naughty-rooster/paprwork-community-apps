#!/bin/bash
set -euo pipefail
OAUTH_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
TOKEN=$(sqlite3 "$OAUTH_DB" "select access_token from oauth_tokens where connection_id='google:personal';")

api_get() {
  local url="$1"; shift
  curl -sS --get -H "Authorization: Bearer $TOKEN" "$url" "$@"
}

sql_escape() { printf "%s" "$1" | sed "s/'/''/g"; }
normalize_email() {
  local s="$1"
  s=$(printf "%s" "$s" | tr '[:upper:]' '[:lower:]')
  local extracted
  extracted=$(printf "%s" "$s" | sed -nE 's/.*<([^>]+)>.*/\1/p')
  if [[ -n "$extracted" ]]; then
    printf "%s" "$extracted"
  else
    printf "%s" "$s" | sed 's/^"//;s/"$//'
  fi
}
name_from_from() {
  local s="$1"
  s=$(printf "%s" "$s" | sed -E 's/[[:space:]]*<[^>]+>//; s/^"//; s/"$//')
  if [[ -z "$s" || "$s" == *"@"* ]]; then
    local e; e=$(normalize_email "$1")
    s=${e%@*}
    s=$(printf "%s" "$s" | sed 's/[._-]/ /g')
  fi
  printf "%s" "$s"
}
org_from_from() {
  local s="$1"
  local name; name=$(name_from_from "$s")
  local email; email=$(normalize_email "$s")
  local domain=${email#*@}
  case "$domain" in
    skellengerbender.com) echo "Skellenger Bender" ;;
    wework.com) echo "WeWork Support" ;;
    outdoorsforall.org) echo "Outdoors for All" ;;
    quicken.com) echo "Quicken" ;;
    chase.com) echo "Chase" ;;
    advancedmd.com) echo "AdvancedMD" ;;
    *) echo "$name" ;;
  esac
}
reason_add() { local key="$1"; reasons["$key"]=$(( ${reasons["$key"]:-0} + 1 )); }
contains_re() { local text="$1" re="$2"; printf "%s" "$text" | tr '[:upper:]' '[:lower:]' | grep -Eiq "$re"; }

query='in:inbox newer_than:4d -category:promotions -category:social'
messages_json=$(api_get 'https://gmail.googleapis.com/gmail/v1/users/me/messages' --data-urlencode 'maxResults=200' --data-urlencode "q=$query")
MESSAGE_IDS=$(printf "%s" "$messages_json" | jq -r '.messages[]?.id')

scanned=0
inserted=0
declare -A reasons
declare -A seen_threads

printf "%s\n" "$MESSAGE_IDS" | while IFS= read -r msg_id; do
  [[ -z "$msg_id" ]] && continue
  scanned=$((scanned+1))
  meta=$(api_get "https://gmail.googleapis.com/gmail/v1/users/me/messages/$msg_id" \
    --data-urlencode 'format=metadata' \
    --data-urlencode 'metadataHeaders=From' \
    --data-urlencode 'metadataHeaders=Subject' \
    --data-urlencode 'metadataHeaders=Date')

  thread_id=$(printf "%s" "$meta" | jq -r '.threadId')
  subject=$(printf "%s" "$meta" | jq -r '([.payload.headers[]? | select(.name=="Subject") | .value][0] // "")')
  from=$(printf "%s" "$meta" | jq -r '([.payload.headers[]? | select(.name=="From") | .value][0] // "")')
  email_date=$(printf "%s" "$meta" | jq -r '([.payload.headers[]? | select(.name=="Date") | .value][0] // "")')
  snippet=$(printf "%s" "$meta" | jq -r '.snippet // ""')
  labels=$(printf "%s" "$meta" | jq -r '(.labelIds // []) | join(",")')
  sender_email=$(normalize_email "$from")
  sender_name=$(name_from_from "$from")
  sender_org=$(org_from_from "$from")
  lc_blob=$(printf "%s %s %s %s" "$subject" "$snippet" "$from" "$labels" | tr '[:upper:]' '[:lower:]')

  existing_message=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where source='gmail' and gmail_message_id='$(sql_escape "$msg_id")';")
  if [[ "$existing_message" != "0" ]]; then reason_add duplicate_message; continue; fi
  if [[ -n "${seen_threads[$thread_id]:-}" ]]; then reason_add duplicate_thread_message; continue; fi
  seen_threads[$thread_id]=1

  if contains_re "$lc_blob" 'terms and conditions|privacy policy|badge!|bill was paid|payment receipt|refund is confirmed|subscription cancel|membership has been cancelled|successfully cancelled|order confirmation|security alert|sign in from a new device|you signed in with a new device|big deposit incoming|large transaction notice|invitation:|accepted:|verification code|verify your .* account|updated our terms|receipt|your refund is confirmed|your bill was paid|payment confirmation|activated|sharing data with quicken'; then
    reason_add informational_or_receipt; continue
  fi
  if contains_re "$lc_blob" 'newsletter|community stories|welcome to|marketing ideas|event image|unsubscribe|opportunity: welcome digital marketing professionals|mailbox linked'; then
    reason_add marketing_or_newsletter; continue
  fi

  similar_open=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where source='gmail' and status='open' and datetime(created_at) > datetime('now','-10 days') and (lower(source_details) like '%$(sql_escape "$sender_email")%' or lower(title) like '%$(sql_escape "$(printf "%s" "$sender_org" | tr '[:upper:]' '[:lower:]')")%');")
  if [[ "$similar_open" != "0" ]]; then reason_add open_similar_task; continue; fi

  thread=$(api_get "https://gmail.googleapis.com/gmail/v1/users/me/threads/$thread_id" \
    --data-urlencode 'format=metadata' \
    --data-urlencode 'metadataHeaders=From' \
    --data-urlencode 'metadataHeaders=Subject' \
    --data-urlencode 'metadataHeaders=Date')

  thread_summary=$(printf "%s" "$thread" | jq -c '[.messages[] | {id, internalDate: (.internalDate|tonumber), from: ([.payload.headers[]? | select(.name=="From") | .value][0] // ""), subject: ([.payload.headers[]? | select(.name=="Subject") | .value][0] // ""), date: ([.payload.headers[]? | select(.name=="Date") | .value][0] // ""), snippet: (.snippet // "")}] | sort_by(.internalDate)')
  last_msg=$(printf "%s" "$thread_summary" | jq -c '.[-1]')
  last_from=$(printf "%s" "$last_msg" | jq -r '.from')
  last_snippet=$(printf "%s" "$last_msg" | jq -r '.snippet')
  last_subject=$(printf "%s" "$last_msg" | jq -r '.subject')
  thread_blob=$(printf "%s" "$thread_summary" | jq -r '[.[].subject, .[].snippet, .[].from] | join(" ")' | tr '[:upper:]' '[:lower:]')

  if contains_re "$thread_blob" 'sounds good|see you then|keep an eye out|will provide an update|we weren.t able to locate it|confirmed|extension filed|done|completed|taken care of|scheduled|paid|submitted|thanks,? got it|thank you,? got it'; then
    reason_add resolved_thread; continue
  fi

  if printf "%s" "$last_from" | tr '[:upper:]' '[:lower:]' | grep -Fq 'cbadcock@gmail.com'; then
    reason_add resolved_by_user_reply; continue
  fi

  ask_text=$(printf "%s %s" "$last_subject" "$last_snippet" | tr '[:upper:]' '[:lower:]')
  if ! contains_re "$ask_text" 'can you|could you|please|let me know|need|resend|send|provide|review|reply|respond|confirm|complete|fill out|upload|share'; then
    reason_add no_explicit_ask; continue
  fi

  title_prefix='Respond to message: '
  target="$sender_org"
  priority=2
  if contains_re "$thread_blob" 'payment|balance due|overdrawn|invoice|billing'; then title_prefix='Make a payment: '; priority=3; fi
  if contains_re "$thread_blob" 'court|legal|order filed|orders filed|motion|case '; then title_prefix='Review legal filing: '; priority=3; fi
  if contains_re "$thread_blob" 'document|attached are the orders|attached'; then title_prefix='Review document: '; fi
  if contains_re "$thread_blob" 'appointment|telehealth|video visit' && contains_re "$thread_blob" 'confirm|reply'; then title_prefix='Confirm appointment: '; fi
  if contains_re "$thread_blob" 'resend|send it|send them|provide|share|we need|need .* account|can you resend'; then title_prefix='Send information: '; target="$sender_name"; fi
  if contains_re "$thread_blob" 'upload'; then title_prefix='Upload document: '; fi
  if contains_re "$thread_blob" 'form'; then title_prefix='Submit form: '; fi
  if contains_re "$thread_blob" 'follow up'; then title_prefix='Follow up with: '; fi

  title="$title_prefix$target"
  description=$(printf 'Email from %s on %s\n\nSubject: %s\n\n%s' "$from" "$email_date" "$subject" "$snippet")
  source_details=$(jq -cn --arg subject "$subject" --arg from "$from" --arg email_date "$email_date" --arg thread_id "$thread_id" '{subject:$subject, from:$from, email_date:$email_date, thread_id:$thread_id}')
  sqlite3 "$ADMIN_DB" "insert into tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) values ('$(sql_escape "$title")','$(sql_escape "$description")',NULL,$priority,'open','gmail','$(sql_escape "$msg_id")','$(sql_escape "$source_details")');"
  inserted=$((inserted+1))
  reason_add inserted
  echo "INSERTED | $msg_id | $title | $from | $subject"
done

echo "SUMMARY scanned=$scanned inserted=$inserted"
for k in "${!reasons[@]}"; do echo "REASON $k=${reasons[$k]}"; done | sort
