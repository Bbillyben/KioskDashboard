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
from django.core.validators import MinValueValidator, MaxValueValidator
import requests

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
        'THEME': {
            'name': _('Theme'),
            'description': _('Select Theme to be displayed'),
            'default': 'white',
            'choices': [
                ('white', 'White'),
                ('dark', 'Dark')
            ],
        },
        'NCBI_KEY': {
            'name': _('NCBI Key'),
            'default': '',
            'description': _('A NCBI API key to request'),
        },
        'NCBI_SEARCH': {
            'name': _('NCBI Search'),
            'default': '',
            'description': _('A search string to request NCBI for'),
        },
        'NCBI_MAX': {
            'name': _('Max Articles'),
            'description': _('set max number of article to show'),
            'default': 5,
            'validator': [int, MinValueValidator(1), MaxValueValidator(10)]
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
    theme = KioskDashboard.get_setting(KioskDashboard(), key="THEME")
    api_key = KioskDashboard.get_setting(KioskDashboard(), key="NCBI_KEY")
    api_search = KioskDashboard.get_setting(KioskDashboard(), key="NCBI_SEARCH")
    api_max = KioskDashboard.get_setting(KioskDashboard(), key="NCBI_MAX")
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
        emp = Employee.objects.filter(pk__in=qset.values_list('employee', flat=True))
        
        curr_leave = Leave.current.all()
        context = {
            "id":1,
            'events': json.dumps(serializers.LeaveSerializer1DCal(qset, many=True).data, cls=DjangoJSONEncoder, ensure_ascii=False),
            'resources': json.dumps(serializers.EmployeeSerialize_Cal(emp, many=True).data, cls=DjangoJSONEncoder, ensure_ascii=False),
            'calendar_dur':int(calendar_dur),
            'theme':theme,
            'leaves':curr_leave,
        }
        
        pages.append({
            "id":1,
            "title":"Absence",
            "html": render(request, f"{KioskDashboard.SLUG}/calendar.html",context ).content.decode('utf-8')
        })
    
    ###### les arrivée prochaines*
    today = datetime.date.today()  # juste la date actuelle
    prev_date = (now + relativedelta(days=-15))
    query= Q(entry_date__gte=prev_date) & Q(entry_date__lte=end_date)
    emp = Employee.objects.filter(query).order_by("entry_date")
    ## Anniversaires du jours
    emp_anniv = Employee.objects.filter(birth_date__month=today.month,
                                    birth_date__day=today.day, is_active = True
                                   ).order_by("first_name")
    if emp.exists() or emp_anniv.exists() or show_empty:
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
            'theme':theme,
            'birthday':emp_anniv,
        }
        pages.append({
            "id":3,
            "title":"Arrivants",
            "html": render(request, f"{KioskDashboard.SLUG}/arrivee.html",context ).content.decode('utf-8')
        })
        
        
    ####"# les derniers Articles
    
    # Étape 1 : Récupérer les PMIDs avec ESearch
    date_filter = f"({now.year-5}[DP]:{now.year}[DP])"
    esearch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={api_search}+AND+{date_filter}&retmax={api_max}&sort=pub+date&api_key={api_key}"
    response = requests.get(esearch_url)
    pmids = response.text.split("<Id>")[1:11]  # On prend les 10 premiers résultats
    pmids = [pmid.split("</Id>")[0] for pmid in pmids]

    
    # Étape 2 : Récupérer les détails des articles avec EFetch
    efetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={','.join(pmids)}&retmode=xml&api_key={api_key}"
    response = requests.get(efetch_url)
    
    # Parser le XML (exemple simplifié)
    articles = []
    if pmids or show_empty:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(response.text)

        for article in root.findall('.//PubmedArticle'):
            title = article.find('.//ArticleTitle').text if article.find('.//ArticleTitle') is not None else "No title"
            authors = ", ".join([author.text for author in article.findall('.//Author/LastName')])
            journal = article.find('.//Journal/Title').text if article.find('.//Journal/Title') is not None else "No journal"
            abstract = article.find('.//AbstractText').text if article.find('.//AbstractText') is not None else "No abstract"
            
            pub_date = ""
            pub_date_element = article.find('.//PubDate')
            if pub_date_element is not None:
                year = pub_date_element.find('Year').text if pub_date_element.find('Year') is not None else ""
                month = pub_date_element.find('Month').text if pub_date_element.find('Month') is not None else ""
                day = pub_date_element.find('Day').text if pub_date_element.find('Day') is not None else ""
                pub_date = f"{day} {month} {year}".strip() if day or month or year else "No date"
            else:
                pub_date = "No date"

            articles.append({
                "title": title,
                "authors": authors,
                "journal": journal,
                "pub_date": pub_date,
                "abstract": abstract,
            })
        
        
        context = {
            "id":4,
            "articles":articles,
            'theme':theme,
        }
        pages.append({
            "id":4,
            "title":"Articles",
            "html": render(request, f"{KioskDashboard.SLUG}/articles.html",context ).content.decode('utf-8')
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