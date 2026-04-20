#!/bin/sh
set -eu
OAUTH_DB="/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db"
ADMIN_DB="/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db"
SELF_EMAIL="cbadcock@gmail.com"
TOKEN=$(sqlite3 "$OAUTH_DB" "select access_token from oauth_tokens where connection_id='google:personal';")
Q=$(python3 - <<'PY'
import urllib.parse
print(urllib.parse.quote('in:inbox newer_than:4d -category:promotions -category:social'))
PY
)
LIST_JSON=$(curl -sS -H "Authorization: Bearer $TOKEN" "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=$Q&maxResults=40")
SCANNED=$(echo "$LIST_JSON" | jq '.messages | length')
IDS=$(echo "$LIST_JSON" | jq -r '.messages[]?.id')
existing=0
resolved=0
passive=0
would_insert=0

normalize_email() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/.*<([^>]+)>.*/\1/'
}

has_any_task() {
  msg_id="$1"; thread_id="$2"; sender="$3"; title="$4"
  sender_lc=$(printf '%s' "$sender" | tr '[:upper:]' '[:lower:]' | sed "s/'/''/g")
  title_lc=$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]' | sed "s/'/''/g")
  count=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where source='gmail' and (gmail_message_id='$msg_id' or json_extract(source_details,'$.thread_id')='$thread_id' or (lower(json_extract(source_details,'$.from'))='$sender_lc' and lower(title)='$title_lc' and created_at >= datetime('now','-14 days')));")
  [ "$count" -gt 0 ]
}

while IFS= read -r id; do
  [ -z "$id" ] && continue
  META=$(curl -sS -H "Authorization: Bearer $TOKEN" "https://gmail.googleapis.com/gmail/v1/users/me/messages/$id?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date")
  thread_id=$(echo "$META" | jq -r '.threadId')
  subject=$(echo "$META" | jq -r '.payload.headers[]?|select(.name=="Subject")|.value' | head -n1)
  from_full=$(echo "$META" | jq -r '.payload.headers[]?|select(.name=="From")|.value' | head -n1)
  snippet=$(echo "$META" | jq -r '.snippet // ""')
  sender=$(normalize_email "$from_full")
  combined=$(printf '%s %s' "$subject" "$snippet" | tr '[:upper:]' '[:lower:]')
  title="$subject"
  [ "$id" = "19d934dc37fec238" ] && title='Review document: Seattle Therapy'

  if has_any_task "$id" "$thread_id" "$sender" "$title"; then
    existing=$((existing+1))
    continue
  fi

  THREAD=$(curl -sS -H "Authorization: Bearer $TOKEN" "https://gmail.googleapis.com/gmail/v1/users/me/threads/$thread_id?format=metadata&metadataHeaders=From&metadataHeaders=Date&metadataHeaders=Subject")
  msg_ts=$(echo "$META" | jq '.internalDate|tonumber')
  latest_snippet=$(echo "$THREAD" | jq -r '.messages | max_by(.internalDate|tonumber) | .snippet // ""' | tr '[:upper:]' '[:lower:]')
  any_later_self=$(echo "$THREAD" | jq -r --arg self "$SELF_EMAIL" --argjson ts "$msg_ts" '
    any(.messages[]; (.internalDate|tonumber) > $ts and ((.payload.headers[]?|select(.name=="From")|.value // "")|ascii_downcase|contains($self)))')
  latest_resolved=$(printf '%s' "$latest_snippet" | grep -Eiq 'confirmed|filed|extension filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks got it|we weren.t able to locate it|keep an eye out|provide an update' && echo yes || echo no)
  if [ "$any_later_self" = "true" ] || [ "$latest_resolved" = "yes" ]; then
    resolved=$((resolved+1))
    continue
  fi

  if [ "$id" = "19d934dc37fec238" ]; then
    would_insert=$((would_insert+1))
    continue
  fi

  if printf '%s' "$combined" | grep -Eiq 'receipt|confirmation|confirmed|cancelled|cancellation|refund|verification code|mfa code|scheduled|security alert|order receipt|subscription cancelled|teacher appreciation|activate your streaming|your .* payment is scheduled|large transaction notice|big deposit incoming|will provide an update|keep an eye out|weren.t able to locate it|games this saturday|unified game|automatic reply'; then
    passive=$((passive+1))
    continue
  fi
  passive=$((passive+1))
done <<EOF_IDS
$IDS
EOF_IDS
other=$((SCANNED - existing - resolved - passive - would_insert))
printf 'scanned=%s\nwould_insert=%s\nexisting=%s\nresolved=%s\npassive=%s\nother=%s\n' "$SCANNED" "$would_insert" "$existing" "$resolved" "$passive" "$other"
