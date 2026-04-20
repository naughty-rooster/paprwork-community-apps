#!/bin/bash
set -euo pipefail
GOOGLE_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ACCESS_TOKEN=$(sqlite3 "$GOOGLE_DB" "SELECT access_token FROM oauth_tokens WHERE connection_id='google:personal';")
Q='in:inbox newer_than:4d -category:promotions -category:social'
TMP=$(mktemp)
curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" --get 'https://gmail.googleapis.com/gmail/v1/users/me/messages' \
  --data-urlencode "q=$Q" --data-urlencode 'maxResults=30' > "$TMP"
jq -r '.messages[]?.threadId' "$TMP" | awk '!seen[$0]++' | while read -r tid; do
  curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" --get "https://gmail.googleapis.com/gmail/v1/users/me/threads/$tid" --data-urlencode 'format=metadata' \
    --data-urlencode 'metadataHeaders=Subject' --data-urlencode 'metadataHeaders=From' --data-urlencode 'metadataHeaders=Date' \
  | jq -r '
      .messages
      | sort_by(.internalDate|tonumber)
      | last as $m
      | [
          $m.id,
          $m.threadId,
          ($m.payload.headers[]|select(.name=="Date")|.value),
          ($m.payload.headers[]|select(.name=="From")|.value),
          ($m.payload.headers[]|select(.name=="Subject")|.value),
          ($m.labelIds|join(",")),
          $m.snippet
        ] | @tsv'
done
