#!/usr/bin/env python
# -*- coding: utf-8; -*-

"""

Script used to migrate trac issues to github with comments.

"""

import os, sys
import csv
import json
import urllib, urllib2
import time
import traceback
import argparse
import re
from signal import signal, SIGINT

def query(url, data, ticket):
    time.sleep(1)
    try:
        return urllib.urlopen(url, data)
    except KeyboardInterrupt:
        raise
    except:
        traceback.print_exc()
        print 'url:', url
        print 'data:', data
        print 'ticket:', ticket

crossref = {}
crossref_pattern = re.compile(r'\#([0-9]+)')
def convert_syntax(string):
    global crossref, crossref_pattern
    for ref in crossref_pattern.findall(string):
        try:
            new = crossref[int(ref)]
            string = string.replace('#%s'%ref, '#%d'%new)
        except KeyError:
            print '  failed to resolve crossreferenced issue', ref, '(ignoring)'
            pass
    return string.replace('{{{', '```').replace('}}}', '```').replace("'''", "**").replace('[[BR]]', '')

try:
    with open('crossref.txt') as fp:
        for line in fp.readlines():
            x,y = line.split(',')
            crossref[int(x)] = int(y)
except IOError:
    pass
crossref_fp = open('crossref.txt', 'w')

parser = argparse.ArgumentParser(description='Migrate issues from trac to github.')
parser.add_argument('-u', '--username', required=True, help='github username')
parser.add_argument('-o', '--orgname', required=False, help='github organization name or username of project')
parser.add_argument('-p', '--project', required=True, help='github project')
parser.add_argument('-a', '--auth', required=True, help='github auth token')
parser.add_argument('tickets', metavar='TICKET.CSV', help='trac tickets as CSV. Use report tool to export (enable all fields)')
parser.add_argument('comments', metavar='COMMENT.CSV', nargs='?')
args = parser.parse_args()

# generate urls for github api
github_url = 'https://github.com/api/v2/json/issues/'
list_open_url = github_url + 'list/%s/%s/open' % (args.orgname, args.project)
list_closed_url = github_url + 'list/%s/%s/closed' % (args.orgname, args.project)
label_add = github_url + 'label/add/%s/%s' % (args.orgname, args.project)
issue_close = github_url + 'close/%s/%s' % (args.orgname, args.project)
comment_add = github_url + 'comment/{orgname}/{project}/{issue}'

tickets = []
class Ticket(object):
    def __init__(self, id, summary, reporter, description, tags, status, comments, gh_issue=None):
        self.id = int(id)
        self.title = summary and summary.encode('utf-8') or None
        self.reporter = reporter
        self.description = description
        self.tags = tags
        self.status = status
        self.comments = comments
        self.gh_issue = gh_issue and int(gh_issue) or None

    def serialize(self):
        return {
            'id': self.id,
            'gh_issue': self.gh_issue,
            'title': self.title,
            'reporter': self.reporter,
            'description': self.description,
            'tags': self.tags,
            'status': self.status,
            'comments': self.comments
        }

    @staticmethod
    def load(title, **kwargs):
        return Ticket(summary=title, **kwargs)

    def upload_ticket(self):
        if self.description is None: return

        self.description = convert_syntax(self.description)
        body = u"""```\nAutomatically imported from Trac.
Originally reported by '{0.reporter}' as #{0.id}.
```

{0.description}
""".format(self)
        
        global args, github_url
        url = github_url + 'open/%s/%s' % (args.orgname, args.project)
        data = urllib.urlencode({
                'login': args.username,
                'token': args.auth,
                'title': self.title,
                'body': body.encode('utf-8'),
        })
        
        response = query(url, data, self)
        content = response.read()
        
        try:
            issue = json.loads(content)['issue']
        except KeyError:
            raise Exception(content)

        self.gh_issue = int(issue['number'])
        self.description = None

        print '  uploaded as github issue #{0.gh_issue}'.format(self)
        
        global crossref, crossref_fp
        crossref[self.id] = self.gh_issue
        crossref_fp.write('%d,%d\n' % (self.id, self.gh_issue))

    def upload_tags(self):
        global args
        data = urllib.urlencode({
            'login': args.username,
            'token': args.auth,
        })

        global label_add
        for tag in self.tags:
            tag = tag.strip()
            if tag in ['', '--']:
                print "  ignoring tag '%s'" % tag
                continue

            try:
                tag = tag.replace(' / ',' ').replace('/', ' ').encode('utf-8')
                url = label_add + '/%s/%d' % (tag, self.gh_issue)
                query(url, data, self)
            except:
                print "  failed to add tag '%s'" % tag
                raise
            print '  added tag', tag
        self.tags = []

    def upload_status(self):
        global args
        if self.status is None: return
        data = urllib.urlencode({
            'login': args.username,
            'token': args.auth,
        })

        st = self.status
        if st in ['new', 'accepted', 'assigned', 'reopened']:
            pass
        elif st == 'closed':
            global issue_close
            url = issue_close + '/%d' % (self.gh_issue)
            query(url, data, ticket)
            print '  marked as closed'
        else:
            raise RuntimeError, 'unkown status "%s"' % st
        self.status = None

    def upload_comments(self):
        global comment_add, args
        n = 0
        while True:
            try:
                author, timestamp, comment = self.comments[0]
            except IndexError:
                break

            n += 1
            body = u"""```
Originally written by '{author}' at {datetime}:
```

{comment}""".format(author=author.encode('utf-8'), datetime=time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(timestamp)), comment=convert_syntax(comment))
            url = comment_add.format(orgname=args.orgname, project=args.project, issue=self.gh_issue)
            data = urllib.urlencode({
                    'login': args.username,
                    'token': args.auth,
                    'comment': body.encode('utf-8')
                    })
            query(url, data, self)
            self.comments.pop(0)

        if n > 0:
            print '  added %d comments' % n

def safe_dict(d):
    if isinstance(d, dict):
        return dict([(k.encode('utf-8'), safe_dict(v)) for k,v in d.iteritems()])
    elif isinstance(d, list):
        return [safe_dict(x) for x in d]
    else:
        return d

if os.path.exists('migration.state'):
    print 'Loading state from migration.state, remove this file it you want to restart'
    with open('migration.state') as fp:
        data = json.load(fp, encoding='utf-8')
        tickets = [Ticket.load(**x) for x in data['tickets']]
        for k,v in data['crossref'].items():
            crossref[int(k)] = int(v)
else:
    # retrieve all existing issues
    data = urllib.urlencode({
            'login': args.username,
            'token': args.auth,
            })
    try:
        response = urllib2.urlopen(list_open_url, data)
        content = response.read()
        issues = json.loads(content)['issues']
    except urllib2.HTTPError, e:
        print >> sys.stderr, 'failed to read existing issues:', e
        print >> sys.stderr, 'url:', list_open_url
        sys.exit(1)
    try:
        response = urllib2.urlopen(list_closed_url, data)
        content = response.read()
        issues += json.loads(content)['issues']
    except urllib2.HTTPError, e:
        print >> sys.stderr, 'failed to read existing issues:', e
        print >> sys.stderr, 'url:', list_closed_url
        sys.exit(1)

    # flatten comments
    comments = {}
    for ticket_id, timestamp, author, body in args.comments is not None and csv.reader(open(args.comments)) or []:
        body = body.strip()
        ticket_id = int(ticket_id)
        timestamp = int(timestamp)
        if not body: continue
        if ticket_id not in comments: comments[ticket_id] = []
        
        body = body
        comments[ticket_id].append((author, timestamp, body))

    # read all trac tickets
    for row in csv.DictReader(open(args.tickets)):
        for key, value in row.items():
            row[key] = row[key].decode('utf-8')
        ticket_id = int(row['id'])

        if filter(lambda i: i['title'] == row['summary'], issues): continue

        row['tags'] = [row['type'], row['component'], row['milestone']]
        del row['type']
        del row['component']
        del row['milestone']
        del row['priority']
        
        tickets.append(Ticket(comments=comments.get(int(row['id']), []), **row))

def persist():
    global tickets, crossref
    with open('migration.state', 'w') as fp:
        json.dump(dict(tickets=[x.serialize() for x in tickets], crossref=crossref), fp)

def sigint_handler(*args):
    print "\rAborting..."
    persist()
    sys.exit(1)

for ticket in tickets:
    print 'processing ticket #{0.id}: {0.title}'.format(ticket)

    try:
        ticket.upload_ticket()
        ticket.upload_tags()
        ticket.upload_status()
    except:
        traceback.print_exc()
        persist()
        sys.exit(1)

for ticket in tickets:
    print 'processing comments for #{0.id}: {0.title}'.format(ticket)

    try:
        ticket.upload_comments()
    except:
        traceback.print_exc()
        persist()
        sys.exit(1)    
