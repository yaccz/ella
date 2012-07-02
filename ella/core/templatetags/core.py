import logging

from django import template
from django.db import models
from django.utils.safestring import mark_safe
from django.template.defaultfilters import stringfilter
from django.contrib.contenttypes.models import ContentType

from ella.core.models import Listing, Category
from ella.core.managers import ListingHandler


log = logging.getLogger('ella.core.templatetags')
register = template.Library()

class ListingNode(template.Node):
    def __init__(self, var_name, parameters):
        self.var_name = var_name
        self.parameters = parameters

    def render(self, context):
        params = {}
        for key, value in self.parameters.items():
            if isinstance(value, template.Variable):
                value = value.resolve(context)
            params[key] = value

        if 'category' in params and isinstance(params['category'], basestring):
            params['category'] = Category.objects.get_by_tree_path(params['category'])


        limits = {}
        if 'offset' in params:
            # templates are 1-based, compensate
            limits['offset'] = params.pop('offset') - 1

        if 'count' in params:
            limits['count'] = params.pop('count')

        lh = Listing.objects.get_queryset_wrapper(**params)

        context[self.var_name] = lh.get_listings(**limits)
        return ''

@register.tag
def listing(parser, token):
    """
    Tag that will obtain listing of top objects for a given category and store them in context under given name.

    Usage::

        {% listing <limit>[ from <offset>][of <app.model>[, <app.model>[, ...]]][ for <category> ] [with children|descendents] [using listing_handler] as <result> %}

    Parameters:
        ==================================  ================================================
        Option                              Description
        ==================================  ================================================
        ``limit``                           Number of objects to retrieve.
        ``offset``                          Starting with number (1-based), starts from first
                                            if no offset specified.
        ``app.model``, ...                  List of allowed models, all if omitted.
        ``category``                        Category of the listing, all categories if not
                                            specified. Can be either string (tree path),
                                            or variable containing a Category object.
        ``children``                        Include items from direct subcategories.
        ``descendents``                     Include items from all descend subcategories.
        ``exclude``                         Variable including a ``Publishable`` to omit.
        ``using``                           Name of Listing Handler ro use
        ``result``                          Store the resulting list in context under given
                                            name.
        ==================================  ================================================

    Examples::

        {% listing 10 of articles.article for "home_page" as obj_list %}
        {% listing 10 of articles.article for category as obj_list %}
        {% listing 10 of articles.article for category with children as obj_list %}
        {% listing 10 of articles.article for category with descendents as obj_list %}
        {% listing 10 from 10 of articles.article as obj_list %}
        {% listing 10 of articles.article, photos.photo as obj_list %}

    """
    var_name, parameters = listing_parse(token.split_contents())
    return ListingNode(var_name, parameters)

LISTING_PARAMS = set(['of', 'for', 'from', 'as', 'using', 'with', 'without', ])

def listing_parse(input):
    params = {}
    if len(input) < 4:
        raise template.TemplateSyntaxError, "%r tag argument should have at least 4 arguments" % input[0]
    o = 1
    # limit
    params['count'] = template.Variable(input[o])
    o = 2

    params['category'] = Category.objects.get_by_tree_path('')
    while o < len(input):
        # offset
        if input[o] == 'from':
            params['offset'] = template.Variable(input[o + 1])
            o = o + 2

        # from - models definition
        elif input[o] == 'of':
            o = o + 1
            mods = []
            while input[o] not in LISTING_PARAMS:
                mods.append(input[o])
                o += 1

            l = []
            for mod in ''.join(mods).split(','):
                m = models.get_model(*mod.split('.'))
                if m is None:
                    raise template.TemplateSyntaxError, "%r tag cannot list objects of unknown model %r" % (input[0], mod)
                l.append(ContentType.objects.get_for_model(m))
            params['content_types'] = l

        # for - category definition
        elif input[o] == 'for':
            params['category'] = template.Variable(input[o + 1])
            o = o + 2

        # with
        elif input[o] == 'with':
            o = o + 1
            if input[o] == 'children':
                params['children'] = ListingHandler.IMMEDIATE
            elif input[o] == 'descendents':
                params['children'] = ListingHandler.ALL
            else:
                raise template.TemplateSyntaxError, "%r tag's argument 'with' required specification (with children|with descendents)" % input[0]
            o = o + 1

        # without (exclude publishable
        elif input[o] == 'without':
            params['exclude'] = template.Variable(input[o + 1])
            o = o + 2

        # using (isting handlers)
        elif input[o] == 'using':
            params['source'] = template.Variable(input[o + 1])
            o = o + 2

        # as
        elif input[o] == 'as':
            var_name = input[o + 1]
            o = o + 2
            break
        else:
            raise template.TemplateSyntaxError('Unknown param for %s: %r' % (input[0], input[o]))
    else:
        raise template.TemplateSyntaxError, "%r tag requires 'as' argument" % input[0]

    if o < len(input):
        raise template.TemplateSyntaxError, "%r tag requires 'as' as last argument" % input[0]

    return var_name, params

class RenderNode(template.Node):
    def __init__(self, var):
        self.var = template.Variable(var)

    def render(self, context):
        try:
            text = self.var.resolve(context)
        except template.VariableDoesNotExist:
            return ''

        template_name = 'render-%s' % self.var
        return template.Template(text, name=template_name).render(context)

@register.tag('render')
def do_render(parser, token):
    """
    Renders a rich-text field using defined markup.

    Example::

        {% render some_var %}
    """
    bits = token.split_contents()

    if len(bits) != 2:
        raise template.TemplateSyntaxError()

    return RenderNode(bits[1])

@register.filter
@stringfilter
def ipblur(text): # brutalizer ;-)
    """ blurs IP address  """
    import re
    m = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}.*', text)
    if not m:
        return text
    return '%sxxx' % m.group(1)

@register.filter
@stringfilter
def emailblur(email):
    "Obfuscates e-mail addresses - only @ and dot"
    return mark_safe(email.replace('@', '&#64;').replace('.', '&#46;'))

