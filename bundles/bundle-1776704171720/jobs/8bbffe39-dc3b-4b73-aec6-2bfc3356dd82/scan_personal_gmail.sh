#!/bin/bash
set -euo pipefail
OAUTH_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
USER_EMAIL='cbadcock@gmail.com'
BASE='https://gmail.googleapis.com/gmail/v1/users/me'
QUERY='in:inbox newer_than:4d -category:promotions -category:social'
TOKEN=$(sqlite3 "$OAUTH_DB" "select access_token from oauth_tokens where connection_id='google:personal';")
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
MSG_FILE="$TMPDIR/messages.tsv"
THREAD_FILE="$TMPDIR/threads.txt"
: > "$MSG_FILE"
sql_escape(){ printf "%s" "$1" | sed "s/'/''/g"; }
sender_email(){ printf "%s" "$1" | sed -n 's/.*<\([^>]*\)>.*/\1/p' | tr '[:upper:]' '[:lower:]'; }
sender_name(){ if [[ "$1" == *"<"* ]]; then printf "%s" "$1" | sed 's/ <.*//' | sed 's/^"//; s/"$//'; else printf "%s" "$1"; fi; }
org_label(){ local name email domain org; name=$(sender_name "$1"); email=$(sender_email "$1"); if [[ -n "$name" && ! "$name" =~ @ ]]; then org="$name"; else domain=$(printf "%s" "$email" | awk -F'@' '{print $2}'); org=$(printf "%s" "$domain" | awk -F'.' '{print $1}' | sed 's/-/ /g; s/_/ /g' | awk '{for(i=1;i<=NF;i++){$i=toupper(substr($i,1,1)) substr($i,2)}}1'); fi; printf "%s" "$(printf "%s" "$org" | sed 's/ Automated Email$//; s/ Notifications$//; s/ Notification$//; s/ Support Services$//')"; }
has_pattern(){ local text="$1"; shift; printf "%s" "$text" | grep -Eiq "$*"; }
page=''; scanned_messages=0
while :; do
  if [[ -n "$page" ]]; then RESP=$(curl -G -fsS -H "Authorization: Bearer $TOKEN" "$BASE/messages" --data-urlencode "q=$QUERY" --data-urlencode 'maxResults=100' --data-urlencode "pageToken=$page"); else RESP=$(curl -G -fsS -H "Authorization: Bearer $TOKEN" "$BASE/messages" --data-urlencode "q=$QUERY" --data-urlencode 'maxResults=100'); fi
  echo "$RESP" | jq -r '.messages[]? | [.id,.threadId] | @tsv' >> "$MSG_FILE"
  count=$(echo "$RESP" | jq '.messages | length')
  scanned_messages=$((scanned_messages + count))
  page=$(echo "$RESP" | jq -r '.nextPageToken // empty')
  [[ -z "$page" ]] && break
done
cut -f2 "$MSG_FILE" | sort -u > "$THREAD_FILE"
scanned_threads=$(wc -l < "$THREAD_FILE" | tr -d ' ')
inserted=0
REASONS="$TMPDIR/reasons.txt"
: > "$REASONS"
add_skip(){ echo "$1" >> "$REASONS"; }
while IFS= read -r tid; do
  [[ -z "$tid" ]] && continue
  THREAD=$(curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/threads/$tid?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date")
  CAND=$(echo "$THREAD" | jq -c --arg me "$USER_EMAIL" '[.messages[] | {id,threadId,internalDate:(.internalDate|tonumber),from:([.payload.headers[]? | select(.name=="From") | .value][0] // ""),subject:([.payload.headers[]? | select(.name=="Subject") | .value][0] // ""),date:([.payload.headers[]? | select(.name=="Date") | .value][0] // ""),snippet:(.snippet // ""),labels:(.labelIds // []),inbound:((([.payload.headers[]? | select(.name=="From") | .value][0] // "") | ascii_downcase | contains($me|ascii_downcase))|not)}] | map(select(.inbound==true)) | if length==0 then empty else max_by(.internalDate) end')
  if [[ -z "$CAND" ]]; then add_skip no_inbound; continue; fi
  mid=$(echo "$CAND" | jq -r '.id'); subject=$(echo "$CAND" | jq -r '.subject'); from=$(echo "$CAND" | jq -r '.from'); email_date=$(echo "$CAND" | jq -r '.date'); snippet=$(echo "$CAND" | jq -r '.snippet'); cand_ts=$(echo "$CAND" | jq -r '.internalDate')
  from_email=$(sender_email "$from"); org=$(org_label "$from"); lower=$(printf '%s %s %s' "$subject" "$snippet" "$from" | tr '[:upper:]' '[:lower:]')
  later_sent=$(echo "$THREAD" | jq --argjson ts "$cand_ts" --arg me "$USER_EMAIL" '[.messages[] | {internalDate:(.internalDate|tonumber),labels:(.labelIds // []),from:([.payload.headers[]? | select(.name=="From") | .value][0] // "")} | select(.internalDate > $ts and ((.labels | index("SENT") != null) or (.from | ascii_downcase | contains($me|ascii_downcase))))] | length')
  if [[ "$later_sent" -gt 0 ]]; then add_skip user_replied; continue; fi
  later_resolved=$(echo "$THREAD" | jq --argjson ts "$cand_ts" '[.messages[] | {internalDate:(.internalDate|tonumber),text:((([.payload.headers[]? | select(.name=="Subject") | .value][0] // "") + " " + (.snippet // "")) | ascii_downcase)} | select(.internalDate > $ts and (.text | test("confirmed|extension filed|filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks[, ]+got it|thank you, got it|thank you got it")))] | length')
  if [[ "$later_resolved" -gt 0 ]]; then add_skip resolved_later; continue; fi
  if has_pattern "$lower" 'automatic reply|out of office|teacher appreciation|game times|receipt|payment confirmation|payment scheduled|sign in|mfa code|verification code|security alert|accepted:|booking submitted|virtual coffee|newsletter|weekly digest|welcome to|activate your streaming subscriptions|keep an eye out|will provide an update|we weren.t able to locate|sounds good|see you then|order receipt|concert|promoted|eligible to move your available credit line|new xfinity sign in|lab test results|video visit is confirmed|starts in approximately 24 hours'; then add_skip noise_or_fyi; continue; fi
  title=''; description=''; due_date='NULL'; priority=2
  if has_pattern "$lower" 'document from|edelivery notification|new message waiting|statement is available|review and sign|review attached|progress note|document available'; then title="Review document: ${org}"; description="Review the document or message from ${org}. Subject: ${subject}."
  elif has_pattern "$lower" 'payment due|past due|overdraft|low balance|final notice|amount due|pay by'; then title="Make a payment: ${org}"; description="Check the payment request from ${org}. Subject: ${subject}."; priority=1
  elif has_pattern "$lower" 'please advise|please let me know|can you|could you|would you|need you to|action required|reply requested|respond by'; then title="Respond to message: ${org}"; description="Respond to ${org}. Subject: ${subject}."
  elif has_pattern "$lower" 'secure message'; then title="Respond to secure message: ${org}"; description="Review and respond to the secure message from ${org}. Subject: ${subject}."
  elif has_pattern "$lower" 'telehealth appointment|appointment confirmation required|confirm appointment'; then if has_pattern "$lower" 'please confirm|confirm your appointment|join telehealth|complete intake|fill out forms'; then title="Confirm appointment: ${org}"; description="Confirm or complete required steps for the appointment from ${org}. Subject: ${subject}."; else add_skip appointment_info_only; continue; fi
  elif has_pattern "$lower" 'upload|send us|send me|send over|provide|submit|complete form|fill out|questionnaire|consent form'; then if has_pattern "$lower" 'upload'; then title="Upload document: ${org}"; elif has_pattern "$lower" 'form|questionnaire|consent'; then title="Submit form: ${org}"; else title="Send information: ${org}"; fi; description="Complete the requested follow-up for ${org}. Subject: ${subject}."
  elif has_pattern "$lower" 'new orders filed|order of child support|final order|legal filing'; then if has_pattern "$lower" 'please advise|please review|you need to|respond'; then title="Review legal filing: ${org}"; description="Review the legal filing-related email from ${org}. Subject: ${subject}."; priority=1; else add_skip legal_update_only; continue; fi
  else add_skip no_clear_action; continue; fi
  exact=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where gmail_message_id='$(sql_escape "$mid")';")
  if [[ "$exact" -gt 0 ]]; then add_skip duplicate_message; continue; fi
  same_thread=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where status='open' and source='gmail' and json_extract(source_details,'$.thread_id')='$(sql_escape "$tid")';")
  if [[ "$same_thread" -gt 0 ]]; then add_skip duplicate_thread; continue; fi
  similar=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where status='open' and created_at >= datetime('now','-14 days') and lower(coalesce(json_extract(source_details,'$.from'),'')) like '%$(sql_escape "$from_email")%' and lower(title)=lower('$(sql_escape "$title")');")
  if [[ "$similar" -gt 0 ]]; then add_skip similar_open_task; continue; fi
  source_details=$(jq -nc --arg subject "$subject" --arg from "$from" --arg email_date "$email_date" --arg thread_id "$tid" '{subject:$subject, from:$from, email_date:$email_date, thread_id:$thread_id}')
  sqlite3 "$ADMIN_DB" "INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) VALUES ('$(sql_escape "$title")','$(sql_escape "$description")',$due_date,$priority,'open','gmail','$(sql_escape "$mid")','$(sql_escape "$source_details")');"
  inserted=$((inserted+1))
done < "$THREAD_FILE"
echo "scanned_messages=$scanned_messages scanned_threads=$scanned_threads inserted=$inserted"
sort "$REASONS" | uniq -c | awk '{print "skip_"$2"="$1}'
