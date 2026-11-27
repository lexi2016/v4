"""Chart geometry is computed from the D slice before any forward data is read."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from research.act067b.charts import DOWN, GRID, INK, LINES, MUTED, UP, font


WIDTH, HEIGHT = 960, 660
LIMIT_COLOR = '#d56e21'
J_COLOR = '#4e62b3'


def geometry(bars, rules):
    if len(bars) != rules['left_sessions']:
        raise ValueError('A locked chart requires its entire D-only slice')
    base = bars[-1].close
    prices = [100*v/base for bar in bars for v in (bar.high,bar.low,bar.w,bar.y,bar.bbi) if v is not None]
    low, high = min(prices), max(prices)
    span = high-low
    pad = max(span*rules['price_padding_fraction'],rules['price_padding_min'])
    prices = [low-pad,high+pad]
    vol = max(b.volume for b in bars)
    j = [bar.j for bar in bars if bar.j is not None]
    j_lo = min([rules['j_min_reference'],*j])-rules['j_padding']
    j_hi = max([rules['j_max_reference'],*j])+rules['j_padding']
    right_extra = (prices[1]-prices[0])*rules['right_price_extra_d_slice_span_fraction']
    return {'d_close_reference':base,'price_ylim':prices,'vol_ylim':[0,vol*rules['vol_axis_scale']],
            'j_ylim':[j_lo,j_hi],'right_price_ylim':[prices[0]-right_extra,prices[1]+right_extra],
            'right_vol_ylim':[0,vol*rules['right_volume_scale_from_d_slice']], 'right_j_ylim':[j_lo,j_hi]}


def render(bars, bounds, rules, *, forward=False):
    required = rules['forward_sessions'] if forward else rules['left_sessions']
    if len(bars) != required:
        raise ValueError('Chart period differs from the frozen window')
    x_low,x_high=84,921
    bounds_key = 'right_' if forward else ''
    base = bounds['d_close_reference']
    bg=tuple(rules['right_background_rgb']) if forward else '#ffffff'
    image=Image.new('RGB',(WIDTH,HEIGHT),bg)
    draw=ImageDraw.Draw(image)
    draw.text((30,19),'Trading sessions D+1 to D+15' if forward else 'Trading sessions through D',fill=INK,font=font(23))
    draw.text((30,53), 'D close = 100   |   Axes fixed at D' if forward else 'D close = 100   |   Trading-session offsets',fill=MUTED,font=font(15))
    for number,(key,color) in enumerate(LINES.items()):
        x=727+number*61
        draw.line((x,61,x+17,61),fill=color,width=3)
        draw.text((x+22,53),key.upper(),fill=MUTED,font=font(13))
    price_top,price_bottom=84,373
    vol_top,vol_bottom=402,484
    j_top,j_bottom=517,606
    step=(x_high-x_low)/required
    xs=[round(x_low+(i+0.5)*step) for i in range(required)]
    half=5 if not forward else 11
    clipping={'price':0,'volume':0,'j':0}

    def project(value, bounds, top, bottom):
        return round(bottom-(max(bounds[0],min(bounds[1],value))-bounds[0])/(bounds[1]-bounds[0])*(bottom-top))

    def ruler(label, lo_hi, top,bottom,ticks,fmt):
        draw.text((x_low-10,top-15),label,anchor='rm',fill=MUTED,font=font(12))
        for i in range(ticks):
            v=lo_hi[0]+i*(lo_hi[1]-lo_hi[0])/(ticks-1)
            y=project(v,lo_hi,top,bottom)
            draw.line((x_low,y,x_high,y),fill=GRID)
            draw.text((x_low-10,y),fmt(v),anchor='rm',fill=MUTED,font=font(12))

    price=bounds[bounds_key+'price_ylim']
    volume=bounds[bounds_key+'vol_ylim']
    j_axis=bounds[bounds_key+'j_ylim']
    ruler('Index',price,price_top,price_bottom,5,lambda v:f'{v:.1f}')
    ruler('Volume',volume,vol_top,vol_bottom,3,lambda v:f'{v/1_000_000:.1f}m' if v>=1_000_000 else f'{v:,.0f}')
    ruler('KDJ J',j_axis,j_top,j_bottom,4,lambda v:f'{v:.0f}')
    if price[0]<=100<=price[1]:
        y_ref=project(100,price,price_top,price_bottom)
        draw.line((x_low,y_ref,x_high,y_ref),fill='#a4afbc',width=1)
    for marker in (13,55,70):
        if j_axis[0] <= marker <= j_axis[1]:
            t=project(marker,j_axis,j_top,j_bottom)
            draw.line((x_low,t,x_high,t),fill='#c5ccd8')
    for key,color,axis,top,bottom,scale in (
        *((key,color,price,price_top,price_bottom,100/base) for key,color in LINES.items()),
        ('j',J_COLOR,j_axis,j_top,j_bottom,1),
    ):
        for first,second,x1,x2 in zip(bars,bars[1:],xs,xs[1:]):
            v1,v2=getattr(first,key),getattr(second,key)
            if v1 is not None and v2 is not None:
                draw.line((x1,project(v1*scale,axis,top,bottom),x2,project(v2*scale,axis,top,bottom)),fill=color,width=2)

    def indicate(x,y,toward_center):
        draw.polygon(((x,y),(x-5,y+toward_center*6),(x+5,y+toward_center*6)),fill=LIMIT_COLOR)

    for i,(bar,x) in enumerate(zip(bars,xs),start=1):
        adj=[100*v/base for v in (bar.open,bar.high,bar.low,bar.close)]
        o,h,l,c=(project(v,price,price_top,price_bottom) for v in adj)
        color=UP if bar.close>bar.open else DOWN if bar.close<bar.open else MUTED
        draw.line((x,h,x,l),fill=color,width=2)
        draw.rectangle((x-half,min(o,c),x+half,max(min(o,c)+1,max(o,c))),fill=color)
        draw.rectangle((x-half,project(bar.volume,volume,vol_top,vol_bottom),x+half,vol_bottom),fill=color)
        if adj[1]>price[1]:
            indicate(x,price_top,1)
        if adj[2]<price[0]:
            indicate(x,price_bottom,-1)
        if adj[1]>price[1] or adj[2]<price[0]:
            clipping['price']+=1
        if bar.volume>volume[1]:
            indicate(x,vol_top,1)
            clipping['volume']+=1
        if bar.j is not None and not j_axis[0]<=bar.j<=j_axis[1]:
            above=bar.j>j_axis[1]
            indicate(x,j_top if above else j_bottom,1 if above else -1)
            clipping['j']+=1
        offset=i if forward else i-required
        if offset in (0,1) or offset%5==0:
            draw.text((x,626),'D' if offset==0 else f'D{offset:+}',anchor='mt',fill=INK,font=font(13))
    if forward and any(clipping.values()):
        draw.text((925,29),f'▲ {sum(clipping.values())} off-scale',anchor='ra',fill=LIMIT_COLOR,font=font(13))
    buffer=BytesIO()
    image.save(buffer,format='PNG',optimize=False)
    return buffer.getvalue(),clipping
