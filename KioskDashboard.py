from django.utils.translation import gettext_lazy as _

from django.urls import re_path, path
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.db.models import Q
from django.db.models import OuterRef, Subquery, Value, TextField
from django.db.models.functions import Concat
from django.contrib.postgres.aggregates import StringAgg

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Value, TextField
from django.db.models.functions import Concat
from django.contrib.postgres.aggregates import StringAgg
from django.core.validators import MinValueValidator
from plugin import LabManagerPlugin
from plugin.mixins import UrlsMixin, SettingsMixin

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

import logging
logger = logging.getLogger("labsmanager.plugin")

from leave.apiviews import LeaveViewSet
from leave.models import Leave
from labsmanager import serializers 
from staff.models import Employee, Employee_Superior
import datetime, json
from dateutil.relativedelta import relativedelta


class KioskDashboard(UrlsMixin, SettingsMixin, LabManagerPlugin):
    NAME = 'KioskDashboard'
    SLUG = 'kiosk'
    Title = _('Kiosk Dashboard')
    AUTHOR = _('LabsManager contributors/Bbillyben')
    DESCRIPTION = _('A plugin to interface with Kiosk Dashboard')
    VERSION = '1.0.1'
    
    SETTINGS = {
        'SLIDE_DURATION': {
            'name': _('Slide Duration'),
            'description': _('duration for each slides in slideshow (in millisec)'),
            'default': 5000,
            'validator': [int, MinValueValidator(3000)]
        },
        
        'RELOAD_INTERVAL': {
            'name': _('Reload Interval'),
            'description': _('reload pages interval(in min)'),
            'default': 10,
            'validator': [int, MinValueValidator(5)]
        },
        'SHOW_EMPTY': {
            'name': _('Show Empty tables'),
            'description': _('Show empty table (if empty)'),
            'default': True,
            'validator': [bool],
        },
        'SHOW_TITLE': {
            'name': _('Show Pages Title'),
            'description': _('Show page title in slideshow'),
            'default': True,
            'validator': [bool],
        },
        'CALENDAR_DUR': {
            'name': _('Calendar view'),
            'description': _('How many days will be displayed in calendar (in days)'),
            'default': 60,
            'validator': [int, MinValueValidator(7)]
        },
     }
    
    def setup_urls(self):
        """Urls that are exposed by this plugin."""
        URLS = [
             path('', view_dash, name='kiosk-dashboard-url'),
        ]

        return URLS

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def view_dash(request):
    ### get the settings 
    duration = KioskDashboard.get_setting(KioskDashboard(), key="SLIDE_DURATION")
    show_empty = KioskDashboard.get_setting(KioskDashboard(), key="SHOW_EMPTY")
    reload_interval = KioskDashboard.get_setting(KioskDashboard(), key="RELOAD_INTERVAL")
    show_title = KioskDashboard.get_setting(KioskDashboard(), key="SHOW_TITLE")
    calendar_dur = KioskDashboard.get_setting(KioskDashboard(), key="CALENDAR_DUR")
    #######   Calendrier des absences
    queryset = Leave.objects.select_related('employee', 'type').all()
    now = datetime.datetime.now()
    start_date = now
    end_date = (now + relativedelta(days=calendar_dur))
    query=Q(start_date__gte=start_date) | (Q(start_date__lt=start_date) & Q(end_date__gte=start_date))
    query2=Q(end_date__lte=end_date) | (Q(start_date__lt=end_date) & Q(end_date__gte=end_date))
    qset = queryset.filter(query)
    qset = qset.filter(query2)
    pages = []
    ## if has a leav or show empty 
    if qset.exists() or show_empty:
        emp = Employee.objects.filter(pk__in=qset.values('employee')).order_by('first_name')
        
        curr_leave = Leave.current.all()
        context = {
            "id":1,
            'events': json.dumps(serializers.LeaveSerializer1DCal(qset, many=True).data, cls=DjangoJSONEncoder, ensure_ascii=False),
            'resources': json.dumps(serializers.EmployeeSerialize_Cal(emp, many=True).data, cls=DjangoJSONEncoder, ensure_ascii=False),
            'calendar_dur':int(calendar_dur),
            'leaves':curr_leave,
        }
        
        pages.append({
            "id":1,
            "title":"Leave Calendar",
            "html": render(request, f"{KioskDashboard.SLUG}/calendar.html",context ).content.decode('utf-8')
        })
    
    #######  Les absent du jour
    # curr_leave = Leave.current.all()
    # # curr_emp = Employee.objects.filter(pk__in=curr_leave.values('employee')).order_by('first_name')
    # if curr_leave.exists() or show_empty:
    #     context = {
    #         "id":2,
    #         'leaves':curr_leave
    #     }
    #     pages.append({
    #         "id":2,
    #         "title":"page 2",
    #         "html": render(request, f"{KioskDashboard.SLUG}/absent.html",context ).content.decode('utf-8')
    #     })
    
    ###### les arrivée prochaines*
    prev_date = (now + relativedelta(days=-15))
    query= Q(entry_date__gte=prev_date) & Q(entry_date__lte=end_date)
    emp = Employee.objects.filter(query).order_by("entry_date")
    if emp.exists() or show_empty:
        # Sous-requête pour concaténer les noms des supérieurs pour chaque employé
        emp = Employee.objects.filter(query).annotate(
            superiors_names=StringAgg(
                Concat(
                    'employee_hierarchy__superior__first_name',
                    Value(' '),
                    'employee_hierarchy__superior__last_name'
                ),
                delimiter=', ',
                distinct=True,
                output_field=TextField()
            )
        ).order_by('entry_date').distinct()
        context = {
            "id":3,
            'employees':emp,
        }
        pages.append({
            "id":3,
            "title":"page 3",
            "html": render(request, f"{KioskDashboard.SLUG}/arrivee.html",context ).content.decode('utf-8')
        })
        
    # if page null then add no data page
    if not pages:
        pages.append({
            "id":1,
            "title":"No Data",
            "html": render(request, f"{KioskDashboard.SLUG}/no_data.html",{} ).content.decode('utf-8')
        })
        
    
    ### construc final json
    data={
        "params":{
            "duration":duration,
            "reload_interval":reload_interval,
            "show_title":show_title,
        },
        "pages": pages,
    }
    
    return JsonResponse(data)