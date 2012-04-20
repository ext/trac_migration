Trac ticket migration
=====================

This script is provided as-is and I take no responsibility for it. That said I have used it successfully a few times.

Usage:
    wget URL/query\?status\=assigned\&status\=closed\&status\=new\&status\=reopened\&format\=csv\&col\=id\&col\=summary\&col\=status\&col\=type\&col\=priority\&col\=milestone\&col\=component\&col\=reporter\&order\=id\&col\=description
    sqlite3 -csv trac.db "select ticket, time, author, newvalue from ticket_change where field = 'comment' and newvalue != '' and author != ''" > comments.csv
    python migrate.py -u USER -o ORG -p PROJECT -a AUTH query.csv commets.csv
