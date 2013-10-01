# -*- coding: utf-8 -*-:
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
import simplejson

from taggit.models import Tag

from resrc.link.models import Link
from resrc.link.forms import NewLinkForm, EditLinkForm, SuggestEditForm
from resrc.list.models import List
from resrc.list.forms import NewListAjaxForm
from resrc.utils import render_template


def single(request, link_pk, link_slug=None):
    from taggit.models import Tag
    link = cache.get('link_%s' % link_pk)
    if link is None:
        link = get_object_or_404(Link, pk=link_pk)
        cache.set('link_%s' % link_pk, link, 60*5)

    titles = []
    newlistform = None

    if link_slug is None:
        return redirect(link)

    # avoid https://twitter.com/this_smells_fishy/status/351749761935753216
    if link.slug != link_slug:
        raise Http404

    reviselinkform = ''
    if request.user.is_authenticated():
        titles = list(List.objects.all_my_list_titles(request.user, link_pk)
                      .values_list('title', flat=True))
        newlistform = NewListAjaxForm(link_pk)
        reviselinkform = SuggestEditForm(link_pk, initial={
            'url': link.url,
            'title': link.title,
            'tags': ','.join([t for t in Tag.objects.filter(link=link_pk).values_list('name', flat=True)]),
            'language': link.language,
            'level': link.level
        })
        # for tag autocomplete
        tags = cache.get('tags_csv')
        if tags is None:
            tags = '","'.join(Tag.objects.all().values_list('name', flat=True))
            tags = '"%s"' % tags
            cache.set('tags_csv', tags, 60*15)

    lists = List.objects.some_lists_from_link(link_pk)

    similars = cache.get('similar_link_%s' % link_pk)
    if similars is None:
        similars = list()
        link_tags = list(link.tags.all())
        max_grams = len(link_tags)
        if max_grams > 10:
            max_grams = 10
        class Enough(Exception): pass
        try:
            for nlen in xrange(max_grams, 1, -1):
                ngram = [link_tags[x:x+nlen] for x in xrange(len(link_tags)-nlen+1)]
                for i in xrange(len(ngram)):
                    igram = ngram[i]
                    add_similars = Link.objects.filter(tags__name=link_tags[0].name)
                    for idx in xrange(1, len(igram)):
                        add_similars = add_similars.filter(tags__name=igram[idx].name)
                    add_similars = add_similars.exclude(pk=link.pk)
                    similars += add_similars
                    similars = list(set(similars))
                    if len(similars) > 10:
                        similars[:10]
                        raise Enough
        except Enough:
            pass
        cache.set('similar_link_%s' % link_pk, similars, 60*60*2)

    tldr = cache.get('tldr_%s' % link_pk)
    if tldr is None:
        try:
            from tldr.tldr import TLDRClient
            client = TLDRClient("victorfelder", "4vle5U5zqElu9xQrsoYC")
            tldr = client.searchByUrl(link.url)
        except:
            tldr = False
        cache.set('tldr_%s' % link_pk, tldr, 60*60*24*8)
    from resrc.vote.models import Vote
    return render_template('links/show_single.html', {
        'link': link,
        'count': Vote.objects.votes_for_link(link.pk),
        'request': request,
        'titles': list(titles),
        'newlistform': newlistform,
        'similars': similars,
        'tldr': tldr,
        'lists': lists,
        'reviselinkform': reviselinkform,
        'tags': tags
    })


@login_required
def new_link(request, title=None, url=None):
    if title is not None and url is not None:
        form = NewLinkForm(initial={
            'title': title,
            'url': url,
        })

        tags = cache.get('tags_csv')
        if tags is None:
            from taggit.models import Tag
            tags = '","'.join(Tag.objects.all().values_list('name', flat=True))
            tags = '"%s"' % tags
            cache.set('tags_csv', tags, 60*15)

        return render_template('links/new_link_button.html', {
            'form': form,
            'tags': tags
        })

    if request.method == 'POST':
        form = NewLinkForm(request.POST)
        if form.is_valid():
            data = form.data

            link = Link()
            link.title = data['title']
            link.url = data['url']
            from resrc.language.models import Language
            link.language = Language.objects.get(language=data['language'])
            link.level = data['level']
            link.author = request.user

            if Link.objects.filter(url=data['url']).exists():
                return redirect(Link.objects.get(url=data['url']).get_absolute_url())

            link.save()
            list_tags = data['tags'].split(',')
            for tag in list_tags:
                link.tags.add(tag)
                cache.delete('tags_all')
                cache.delete('tags_csv')
            link.save()

            if not 'ajax' in data:
                return redirect(link.get_absolute_url())

            alist = get_object_or_404(List, pk=data['id'])
            # if alist.owner != request.user:
            #    raise Http404
            from resrc.list.models import ListLinks
            if not ListLinks.objects.filter(alist=alist, links=link).exists():
                ListLinks.objects.create(
                    alist=alist,
                    links=link
                )
            from resrc.utils.templatetags.emarkdown import listmarkdown
            alist.html_content = listmarkdown(alist.md_content, alist)
            alist.save()

            data = simplejson.dumps({'result': 'added'})
            return HttpResponse(data, mimetype="application/javascript")
        else:
            if not 'ajax' in form.data:
                form = NewLinkForm()

                tags = cache.get('tags_csv')
                if tags is None:
                    from taggit.models import Tag
                    tags = '","'.join(Tag.objects.all().values_list('name', flat=True))
                    tags = '"%s"' % tags
                    cache.set('tags_csv', tags, 60*15)

                return render_template('links/new_link.html', {
                    'form': form,
                    'tags': tags
                })
            else:
                data = simplejson.dumps({'result': 'fail'})
                return HttpResponse(data, mimetype="application/javascript")

    else:
        form = NewLinkForm()

    tags = cache.get('tags_csv')
    if tags is None:
        from taggit.models import Tag
        tags = '","'.join(Tag.objects.all().values_list('name', flat=True))
        tags = '"%s"' % tags
        cache.set('tags_csv', tags, 60*15)

    return render_template('links/new_link.html', {
        'form': form,
        'tags': tags
    })


@login_required
def edit_link(request, link_pk):
    link = cache.get('link_%s' % link_pk)
    if link is None:
        link = get_object_or_404(Link, pk=link_pk)
        cache.set('link_%s' % link_pk, link, 60*5)
    if request.user != link.author:
        raise Http404
    if request.method == 'POST':
        form = EditLinkForm(link_pk, request.POST)
        if form.is_valid():
            link.title = form.data['title']
            from resrc.language.models import Language
            link.language = Language.objects.get(
                language=form.data['language'])
            link.level = form.data['level']
            link.author = request.user

            has_tags = link.tags.all().values_list('name', flat=True)

            link.save()
            list_tags = form.data['tags'].split(',')
            for tag in list_tags:
                if tag not in has_tags:
                    link.tags.add(tag)
            for tag in has_tags:
                if tag not in list_tags:
                    link.tags.remove(tag)
            link.save()
            return redirect(link.get_absolute_url())
        else:
            form = EditLinkForm(link_pk=link_pk, initial={
                'url': link.url,
                'title': link.title,
                'tags': ','.join([t for t in Tag.objects.filter(link=link_pk).values_list('name', flat=True)]),
                'language': link.language,
                'level': link.level
            })

            tags = cache.get('tags_csv')
            if tags is None:
                from taggit.models import Tag
                tags = '","'.join(Tag.objects.all().values_list('name', flat=True))
                tags = '"%s"' % tags
                cache.set('tags_csv', tags, 60*15)

            return render_template('links/new_link.html', {
                'edit': True,
                'form': form,
                'tags': tags
            })

    else:
        form = EditLinkForm(link_pk=link_pk, initial={
            'url': link.url,
            'title': link.title,
            'tags': ','.join([t for t in Tag.objects.filter(link=link_pk).values_list('name', flat=True)]),
            'language': link.language,
            'level': link.level
        })

    tags = cache.get('tags_csv')
    if tags is None:
        from taggit.models import Tag
        tags = '","'.join(Tag.objects.all().values_list('name', flat=True))
        tags = '"%s"' % tags
        cache.set('tags_csv', tags, 60*15)

    return render_template('links/new_link.html', {
        'edit': True,
        'form': form,
        'tags': tags
    })


def ajax_upvote_link(request, link_pk, list_pk=None):
    if request.user.is_authenticated() and request.method == 'POST':
        link = cache.get('link_%s' % link_pk)
        if link is None:
            link = get_object_or_404(Link, pk=link_pk)
            cache.set('link_%s' % link_pk, link, 60*5)

        from resrc.vote.models import Vote
        already_voted = Vote.objects.filter(
            user=request.user, link=link).exists()
        if not already_voted:
            link.vote(request.user, list_pk)
            data = simplejson.dumps({'result': 'success'})
            return HttpResponse(data, mimetype="application/javascript")
        else:
            data = simplejson.dumps({'result': 'fail'})
            return HttpResponse(data, mimetype="application/javascript")
    raise Http404


def ajax_revise_link(request, link_pk):
    link = cache.get('link_%s' % link_pk)
    if link is None:
        link = get_object_or_404(Link, pk=link_pk)
        cache.set('link_%s' % link_pk, link, 60*5)

    if request.user.is_authenticated() and request.method == 'POST':
        form = SuggestEditForm(link_pk, request.POST)
        data = form.data
        # we only store the differences
        title = data['title']
        if link.title == title:
            title = ''
        url = data['url']
        if link.url == url:
            url = ''
        from resrc.language.models import Language
        language = Language.objects.get(language=data['language'])
        if link.language == language:
            language = None
        level = data['level']
        if link.level == level:
            level = ''
        from resrc.link.models import RevisedLink
        rev = RevisedLink.objects.create(
            link=link,
            title=title,
            url=url,
            language=language,
            level=level,
            tags=form.data['tags']
        )
        rev.save()
        data = simplejson.dumps({'result': 'success'})
        return HttpResponse(data, mimetype="application/javascript")
    else:
        raise Http404


def links_page(request):
    from resrc.vote.models import Vote
    latest = Vote.objects.latest_links(limit=25, days=7)
    hottest = Vote.objects.hottest_links(limit=15, days=7)
    most_voted = Vote.objects.hottest_links(limit=10, days=30)

    return render_template('links/links.html', {
        'latest': latest,
        'hottest': hottest,
        'most_voted': most_voted,
    })
