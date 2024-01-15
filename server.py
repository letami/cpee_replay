#!/usr/bin/python3
import logging
import os.path
import random
import sqlite3
import json
import yaml
import numpy as np
from sklearn.svm import SVC
from sklearn.model_selection import train_test_split
from sqlite3 import Error
from bottle import route, request, response, run, template, error, post, get, static_file

logger = logging.getLogger('web')
logger.setLevel(logging.INFO)


@error()
def error(error):
    return template('<b>There was an error: {{error}}', error=error)


@route('/')
def default():
    return "This is the landing page"


@route('/logs')
def uploadLogs():
    return static_file('html/uploadLogs.html', root='.')


@post('/logs')
def doUpload():
    uploads = request.files.getall('upload')
    for upload in uploads:
        name, ext = os.path.splitext(upload.filename)
        if ext not in '.yaml':
            return 'File is not a YAML file. Upload not possible'
        data = list(yaml.safe_load_all(upload.file))

        conn = None
        try:
            conn = sqlite3.connect(r'db/logs.db')
        except Error as e:
            return 'Could not connect to db'
        cur = conn.cursor()

        keyList = ['cpee:activity_uuid', 'id:id', 'concept:name', 'concept:endpoint', 'lifecycle:transition',
                   'cpee:lifecycle:transition', 'data', 'time:timestamp', 'concept:instance']

        for entry in data[1:]:
            filteredEntry = dict((k, entry['event'][k]) for k in keyList if k in entry['event'])
            keyDict = dict.fromkeys(keyList, 'None')
            if 'raw' in entry['event']:
                filteredEntry['data'] = entry['event']['raw']

            for key in filteredEntry:
                if key in 'data':
                    keyDict[key] = json.dumps(filteredEntry[key])
                else:
                    keyDict[key] = filteredEntry[key]

            eventSql = 'INSERT INTO events(task_id, task, task_desc, endpoint, lifecycle, cpee_life, data, time, log_id) VALUES (?,?,?,?,?,?,?,?,?);'
            cur.execute(eventSql, tuple(keyDict.values()))
        conn.commit()
    return 'Upload successful'


@post('/replay')
@get('/replay')
def replay():
    conn = None
    try:
        conn = sqlite3.connect(r'db/logs.db')
    except Error:
        return 'Could not connect to db'
    cur = conn.cursor()

    dataDictList = []
    for i in request.forms:
        try:
            dataNumber = int(request.forms[i])
        except ValueError:
            try:
                dataNumber = float(request.forms[i])
            except ValueError:
                dataNumber = request.forms[i]
        newDict = {"name": i, "value": dataNumber}
        dataDictList.append(newDict)

    task = {
        'og_endpoint': request.query['original_endpoint'],
        'data': dataDictList
    }

    eventQuery = 'SELECT * FROM EVENTS WHERE endpoint=? AND cpee_life=?'
    cur.execute(eventQuery, (task['og_endpoint'], 'activity/calling'))

    try:
        eventList = cur.fetchall()
    except IndexError:
        response.status = 404
        return 'No corresponding entry in a logfile found'

    useSVM = False

    filteredEventList = []

    for i in eventList:
        if i[7] == json.dumps(task['data']) or (i[7] == 'null' and task['data'] == []):
            filteredEventList.append(i)
        else:
            if isinstance(json.loads(i[7]), list) and isinstance(task['data'], list):
                for j in json.loads(i[7]):
                    isIdSame = False
                    for k in task['data']:
                        if j['name'] == k['name']:
                            isIdSame = True
                            break
                    if not isIdSame:
                        return 'No corresponding entry in logfile found'
            elif isinstance(json.loads(i[7]), dict):
                for key in json.loads(i[7]):
                    isIdSame = False
                    for j in task['data']:
                        if key == j['name']:
                            isIdSame = True
                            break
                    if not isIdSame:
                        return 'No corresponding entry in logfile found'
            filteredEventList.append(i)
            #useSVM = True

    event = random.choice(filteredEventList)

    if useSVM:
        classifier = svm(event)
        dataName = dataDictList[0]['value']
        if isinstance(classifier, str):
            if classifier == 'None':
                return ''
            returnValue = classifier
        else:
            returnValue = classifier.predict([[dataName]])[0]

        response.headers['Content-Type'] = 'application/x-www-form-urlencoded'
        return 'test=hello&' + dataName + '=' + returnValue

    logID = event[9]
    taskID = event[2]

    returnQuery = 'SELECT * FROM EVENTS WHERE log_id=? AND task=? AND cpee_life IN ("activity/receiving", "task/instantiation")'
    cur.execute(returnQuery, (logID, taskID))

    returnEventList = cur.fetchall()

    if list(filter(lambda x: (x[6] == 'task/instantiation'), returnEventList)):
        response.status = 561
        return ''

    returnEvent = random.choice(returnEventList)

    if returnEvent[7] == 'None':
        response.status = 200
        return ''

    returnData = json.loads(returnEvent[7])
    returnStr = ''
    for i in returnData:
        returnStr += i['name'] + '=' + i['data'] + '&'

    response.headers['Content-Type'] = 'application/x-www-form-urlencoded'

    return returnStr[:-1]


def svm(event):
    conn = None
    try:
        conn = sqlite3.connect(r'db/logs.db')
    except Error as e:
        return 'Could not connect to db'
    cur = conn.cursor()

    eventQuery = 'SELECT * FROM EVENTS WHERE task=? AND endpoint=? AND cpee_life IN ("activity/calling", "activity/receiving")'
    cur.execute(eventQuery, (event[2], event[4]))

    dataEventList = cur.fetchall()

    sampleList = list(filter(lambda x: (x[6] == 'activity/calling'), dataEventList))
    labelList = list(filter(lambda x: (x[6] == 'activity/receiving'), dataEventList))
    sampleList.sort(key=lambda a: a[1])
    labelList.sort(key=lambda a: a[1])

    sampleArray = []
    for i in sampleList:
        sampleArray.append([json.loads(i[7])[0]['value']])

    labelArray = []
    for i in labelList:
        if i[7] == 'None':
            labelArray.append('None')
        else:
            labelArray.append(json.loads(i[7])[1]['data'])

    X = np.array(sampleArray)
    y = np.array(labelArray)

    if len(np.unique(y)) == 1:
        return y[0]
    else:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3)

        classifier = SVC(kernel='linear')
        classifier.fit(X_train, y_train)

        return classifier


run(host='::', port=17001)
