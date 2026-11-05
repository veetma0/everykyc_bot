"""Export actual bot cards to an offline, interactive Telegram layout preview.

Run with .venv/bin/python scripts/render_ui_preview.py. No Telegram connection,
credentials, customer records, or network requests are used.
"""

from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verifydesk import catalog, rules, screens, ui  # noqa: E402
from verifydesk.store import OPEN_STATUSES, Store  # noqa: E402


def card(value):
    text, keyboard = value
    return {"text": text, "rows": keyboard.to_dict()["inline_keyboard"] if keyboard else []}


def export_cards():
    cards = {"c:home": card(ui.home("Эврикус", None)),
             "c:catalog": card(screens.catalog_card()),
             "c:help": card(screens.help_card()),
             "c:privacy": card((ui.PRIVACY, ui.Keyboard([[ui.action("Главная", "c:home")]])))}
    for category in catalog.CATEGORIES:
        offers = screens.category_offers(category)
        for page in range((len(offers) + screens.CATALOG_PAGE_SIZE - 1) // screens.CATALOG_PAGE_SIZE):
            cards[f"c:category:{category}:{page}"] = card(screens.category_card(category, page))
        cards[f"c:category:{category}"] = cards[f"c:category:{category}:0"]
    for offer in catalog.OFFERS.values():
        cards[f"c:service:{offer.service}"] = card(screens.offer_card(offer))
        cards[f"c:guide:{offer.service}"] = card((screens.guide(offer.service), ui.Keyboard([
            [ui.action("‹ К заказу", "c:current")],
        ])))
    cards["c:guide:general"] = card((screens.guide("general"), ui.Keyboard([
        [ui.action("Каталог услуг", "c:catalog")],
        [ui.action("‹ Помощь", "c:help"), ui.action("Главная", "c:home")],
    ])))
    for page in range(len(rules.PAGES)):
        cards[f"c:rules:{rules.VERSION}:{page}"] = card(rules.card(page, accepted=True))
    cards["c:rules"] = cards[f"c:rules:{rules.VERSION}:0"]
    samples, examples = {}, {}
    for page in range(len(rules.PAGES)):
        examples[f"onboarding:{page}"] = card(rules.card(page))
    with TemporaryDirectory(prefix="everykyc-preview-") as directory:
        store = Store(Path(directory) / "preview.sqlite3")
        store.remember_user(1, 1, "Пример клиента", None)
        empty = store.profile(1)
        cards["c:profile"] = card(screens.profile_card(empty, None, "UTC"))
        ticket, _ = store.create_ticket(1, "bybit", "standard", "50.00")
        profile = store.profile(1)
        store.add_message(ticket.id, "user", "Здравствуйте! Нужна помощь с проверкой моего аккаунта.", 1, 1, 1)
        store.add_message(ticket.id, "operator", "Пример ответа: уточните страну и текст ошибки без личных данных.",
                          2, 2, 2)
        history_rows, history_total = store.messages(ticket.id)
        examples["history_customer"] = card(ui.history(ticket, history_rows, history_total, 0, False, "UTC"))
        examples["history_admin"] = card(ui.history(ticket, history_rows, history_total, 0, True, "UTC"))
        examples["admin_home"] = card(ui.admin_home(
            {"new": 2, "in_progress": 1, "waiting_user": 0, "resolved": 1, "cancelled": 0},
            queue_count=3, stages={"review": 1},
        ))
        examples["admin_more"] = card(ui.admin_more())
        for offer in catalog.OFFERS.values():
            if not offer.available:
                continue
            current = replace(ticket, service_code=offer.service, price_usd=offer.price_usd)
            payment = replace(current, payment_stage="awaiting_payment")
            rejected = replace(payment, has_payment_proof=True)
            review = replace(current, payment_stage="review", has_payment_proof=True)
            working = replace(current, status="in_progress", payment_stage="confirmed", has_payment_proof=True)
            done = replace(working, status="resolved")
            stages = {"new": current, "payment": payment, "rejected": rejected,
                      "review": review, "working": working, "done": done}
            samples[offer.service] = {name: card(ui.customer_ticket(sample, "UTC"))
                                     for name, sample in stages.items()}
            samples[offer.service]["context"] = {}
            for name, sample in stages.items():
                active = sample if sample.status in OPEN_STATUSES else None
                summary = replace(profile, active_tickets=int(active is not None),
                                  resolved_tickets=int(sample.status == "resolved"))
                samples[offer.service]["context"][name] = {
                    "home": card(ui.home("Эврикус", active)),
                    "profile": card(screens.profile_card(summary, active, "UTC")),
                    "help": card(screens.help_card(active)),
                }
            if offer.service == "bybit":
                for name, sample in stages.items():
                    examples[f"admin_ticket:{name}"] = card(ui.admin_ticket(sample))
                    examples[f"admin_details:{name}"] = card(ui.admin_details(sample))
                    examples[f"admin_status:{name}"] = card(ui.status_menu(sample))
                examples["admin_ticket:review_ready"] = card(ui.admin_ticket(review, proof_ready=True))
                examples["admin_profile"] = card(screens.profile_card(profile, current, "UTC", admin=True))
                for delivery in ("delivered", "uncertain", "failed"):
                    examples[f"reply:{delivery}"] = card(ui.reply_receipt(working, delivery))
                examples["review_request"] = card(ui.review_request(done))
                examples["review_comment"] = card(ui.review_comment_card(done, 5))
        store.close()
    return {"cards": cards, "samples": samples, "examples": examples,
            "services": {o.service: o.title for o in catalog.OFFERS.values() if o.available}}


HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Эврикус · проверка интерфейса</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6f7;color:#182129;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:28px 28px 16px;max-width:1500px;margin:auto}h1{font-size:24px;line-height:1.2;letter-spacing:-.5px;margin:0 0 7px;font-weight:650}
.note{margin:0;color:#4a5863;max-width:900px}.controls{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin-top:20px}label{display:flex;gap:5px;flex-direction:column;font-size:12px;color:#4a5863}
select,.reset{border:1px solid #b9c5cc;border-radius:7px;background:white;padding:9px 11px;font:14px inherit;color:#182129;min-height:40px}.reset{cursor:pointer}
.live-note{min-height:36px;margin:10px 0 0;font-size:13px;color:#495c6b}.frames{display:grid;grid-template-columns:320px 390px 320px 390px;justify-content:center;align-items:start;gap:14px;padding:0 16px 32px;overflow-x:auto}
.frame{min-width:0}h2{font-size:13px;font-weight:500;margin:0 0 8px;color:#495c6b}.phone{height:735px;border:1px solid #bfc9ce;border-radius:19px;overflow:hidden;background:#dfe7e9;display:flex;flex-direction:column;box-shadow:0 2px 8px #10232e08}
.statusbar{height:25px;display:flex;justify-content:space-between;align-items:center;padding:4px 17px 0;background:#fff;font-size:11px;font-weight:600}.chatbar{background:#fff;display:flex;align-items:center;gap:10px;height:62px;flex:none;padding:10px 14px;border-bottom:1px solid #e2e7eb}.back{font-size:30px;color:#388cc2;line-height:1}.avatar{width:37px;height:37px;display:grid;place-items:center;background:#4388a0;color:white;border-radius:50%;font-size:20px;font-weight:600}.identity strong{font-size:15px;display:block}.identity span{display:block;color:#7b8a94;font-size:12px}.dots{margin-left:auto;font-size:20px;color:#7b8a94}
.chat{padding:17px 9px 20px;overflow:auto;flex:1;scrollbar-width:thin;overscroll-behavior:contain}.date{display:table;margin:0 auto 14px;padding:2px 8px;border-radius:10px;color:#fff;background:#91a3a9;font-size:11px}.bubble{padding:11px 12px 16px;border-radius:12px 12px 12px 4px;background:#fff;font-size:14px;line-height:1.38;overflow-wrap:anywhere;position:relative;white-space:pre-wrap}.bubble b{font-weight:650}.bubble code{font-family:ui-monospace,monospace;font-size:13px}.time{position:absolute;bottom:3px;right:9px;font-size:10px;color:#96a0a7}
.keyboard{display:flex;flex-direction:column;gap:4px;margin-top:4px}.row{display:flex;gap:4px}.key{min-width:0;flex:1;min-height:42px;padding:9px 5px;border:0;border-radius:6px;background:#ffffffdc;color:#255d7f;font-family:inherit;font-size:14px;font-weight:500;line-height:1.15;white-space:nowrap;cursor:pointer;overflow:hidden;text-overflow:ellipsis}.key:hover{background:#fff}.key:active{transform:translateY(1px)}.key:focus-visible{outline:2px solid #168ad1;outline-offset:-2px}
.composer{height:51px;flex:none;background:#fff;display:flex;align-items:center;gap:10px;padding:8px 12px;color:#8f9da5;font-size:23px}.input{background:#f1f3f5;border-radius:17px;padding:6px 11px;flex:1;font-size:14px;color:#98a1a8}.dark .phone{border-color:#344454;background:#101b28}.dark .statusbar,.dark .chatbar,.dark .composer{background:#172432;color:#e3ebf1}.dark .chatbar{border-color:#203343}.dark .bubble{background:#203142;color:#edf2f7}.dark .key{background:#21384b;color:#e3eef7}.dark .key:hover{background:#2c455a}.dark .date{background:#1f3346;color:#b9c8d3}.dark .input{background:#213345}.dark .time{color:#90a5b4}
footer{padding:0 28px 25px;color:#53636e;font-size:12px;max-width:1500px;margin:auto}a{color:#287ca5}button,select{touch-action:manipulation}@media(max-width:1490px){.frames{grid-template-columns:320px 390px}}@media(max-width:760px){header{padding:20px 16px 12px}.frames{grid-template-columns:320px;justify-content:center}.frame.wide{display:none}.controls{gap:8px}select{max-width:100%}h1{font-size:21px}}
</style></head><body>
<header><h1>Эврикус · проверка интерфейса</h1><p class="note">Локальный макет · реальные тексты и кнопки бота. Каталог и навигация доступны для просмотра; примеры заказов не отправляются оператору. Это не снимок Telegram.</p>
<div class="controls"><label>Открыть экран<select id="screen"><option value="c:home">Главная</option><option value="c:catalog">Каталог</option><option value="c:category:exchanges">Биржи</option><option value="c:category:other">Прочие сервисы</option><option value="c:help">Помощь</option><option value="c:profile">Мои заказы</option><option value="c:rules">Правила</option><option value="c:privacy">Мои данные</option></select></label>
<label>Пример заказа<select id="state"><option value="">Без заказа</option><option value="new">Ожидает оператора</option><option value="payment">Ожидает оплаты</option><option value="rejected">Нужен другой чек</option><option value="review">Проверяем оплату</option><option value="working">В работе</option><option value="done">Заказ выполнен</option></select></label><label>Сервис в примере<select id="service"></select></label><label>Другие экраны · пример Bybit<select id="example"><option value="">Выбрать экран</option></select></label><button class="reset" id="reset">Начать сначала</button></div>
<p class="live-note" id="notice" role="status">Нажимайте кнопки в любом из четырёх окон — остальные покажут тот же экран.</p></header>
<main class="frames" id="frames"></main><footer>Ширина 320 и 390 px · светлая и тёмная темы. Оформление приближено к Telegram для проверки длины строк; реальные шрифты и размеры зависят от устройства. Фирменные эмодзи бирж проверяются в Telegram отдельно. Макет не обращается к сети.</footer>
<script id="data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.querySelector('#data').textContent);let route='c:home',state='',service='bybit';
const notice=document.querySelector('#notice'),screen=document.querySelector('#screen'),stateSelect=document.querySelector('#state'),serviceSelect=document.querySelector('#service'),exampleSelect=document.querySelector('#example');
for(const [code,title] of Object.entries(data.services)){const option=document.createElement('option');option.value=code;option.textContent=title;serviceSelect.append(option)}
const exampleLabels={'onboarding:0':'Первый вход · правила 1/4','onboarding:1':'Правила 2/4','onboarding:2':'Правила 3/4','onboarding:3':'Правила · согласие','history_customer':'Переписка клиента','history_admin':'Переписка оператора','admin_home':'Кабинет оператора','admin_more':'Оператор · ещё','admin_profile':'Карточка клиента','review_request':'Оценка заказа','review_comment':'Комментарий к оценке','reply:delivered':'Ответ доставлен','reply:uncertain':'Доставка не подтверждена','reply:failed':'Ответ не доставлен'};
const stageLabels={new:'новый',payment:'ожидает оплаты',rejected:'нужен другой чек',review:'чек на проверке',review_ready:'чек просмотрен',working:'в работе',done:'завершён'};for(const key of Object.keys(data.examples)){const option=document.createElement('option');option.value='x:'+key;const [kind,stage]=key.split(':');option.textContent=exampleLabels[key]||`${{admin_ticket:'Заказ оператора',admin_details:'Детали',admin_status:'Статус'}[kind]||kind} · ${stageLabels[stage]||stage}`;exampleSelect.append(option)}
for(const [width,dark] of [[320,false],[390,false],[320,true],[390,true]]){const frame=document.createElement('section');frame.className=`frame ${width===390?'wide':''} ${dark?'dark':''}`;frame.innerHTML=`<h2>${width} px · ${dark?'тёмная':'светлая'} тема</h2><div class="phone"><div class="statusbar"><span>9:41</span><span>▴ ▰</span></div><div class="chatbar"><span class="back">‹</span><div class="avatar">Э</div><div class="identity"><strong>Эврикус</strong><span>бот</span></div><span class="dots">⋮</span></div><div class="chat"><span class="date">Сегодня</span><div class="bubble"></div><div class="keyboard"></div></div><div class="composer"><span>＋</span><span class="input">Сообщение</span><span>◉</span></div></div>`;document.querySelector('#frames').append(frame)}
function currentCard(){if(route.startsWith('x:'))return data.examples[route.slice(2)];if(state){const sample=data.samples[service];if(route==='c:home')return sample.context[state].home;if(route==='c:profile')return sample.context[state].profile;if(route==='c:help')return sample.context[state].help;if(route==='c:current'||route.startsWith('c:view:')||route.startsWith('c:chat:'))return sample[state]}return data.cards[route]||data.cards['c:home']}
function show(next){route=next;const found=currentCard();screen.value=[...screen.options].some(o=>o.value===next)?next:'';stateSelect.value=state;serviceSelect.value=service;exampleSelect.value=route.startsWith('x:')?route:'';serviceSelect.disabled=route.startsWith('x:');for(const frame of document.querySelectorAll('.frame')){frame.querySelector('.bubble').innerHTML=found.text+'<span class="time">9:41</span>';const keyboard=frame.querySelector('.keyboard');keyboard.replaceChildren();for(const buttons of found.rows){const row=document.createElement('div');row.className='row';for(const item of buttons){const key=document.createElement('button');key.className='key';key.textContent=item.text;key.title=item.text;key.dataset.callback=item.callback_data||'';key.onclick=()=>navigate(item.callback_data);row.append(key)}keyboard.append(row)}frame.querySelector('.chat').scrollTop=0}history.replaceState(null,'','#'+encodeURIComponent(next));}
function navigate(next){notice.textContent='Нажимайте кнопки в любом окне — все темы и размеры обновляются вместе.';if(route.startsWith('x:onboarding:')&&next.startsWith('c:rules:')){show('x:onboarding:'+next.split(':').at(-1));return}if(next.startsWith('c:agree:')){state='';show('c:home');notice.textContent='Это только просмотр: согласие не сохраняется.';return}if(next.startsWith('c:rate:')){show('x:review_comment');notice.textContent='Показан пример комментария к оценке. Отзыв не сохраняется.';return}if(next.startsWith('c:history:')){show('x:history_customer');return}if(next.startsWith('a:history:')){show('x:history_admin');return}if(next.startsWith('c:order:')){service=next.split(':')[2];state='new';notice.textContent='Показан образец нового заказа. Это только локальный просмотр: заявка не создана, сообщений и оплаты нет.';show('c:current');return}const adminRoutes={'a:home':'admin_home','a:more':'admin_more','a:mode:admin':'admin_home'};if(adminRoutes[next]){show('x:'+adminRoutes[next]);return}if(next.startsWith('a:view:')||next.startsWith('a:next')){show('x:admin_ticket:new');return}if(next.startsWith('a:client:')){show('x:admin_profile');return}if(next.startsWith('a:details:')){show('x:admin_details:working');return}if(next.startsWith('a:status:')){show('x:admin_status:working');return}if(data.cards[next]||next==='c:current'||next.startsWith('c:view:')||next.startsWith('c:chat:')){if(next.startsWith('c:view:')&&!state)state='new';show(next);return}notice.textContent='Это действие не выполняется в локальном макете. Нужный пример состояния можно открыть в списке «Другие экраны».';}
screen.onchange=()=>navigate(screen.value);exampleSelect.onchange=()=>{if(exampleSelect.value){show(exampleSelect.value);notice.textContent='Локальный пример Bybit: данные вымышлены, действий в Telegram нет.'}};stateSelect.onchange=()=>{state=stateSelect.value;notice.textContent=state?'Показан только образец состояния заказа. Реальных заказов и платежей нет.':'Показан интерфейс без активного заказа.';show(state?'c:current':'c:home')};serviceSelect.onchange=()=>{service=serviceSelect.value;show(state?'c:current':`c:service:${service}`)};document.querySelector('#reset').onclick=()=>{state='';service='bybit';navigate('c:home')};
const params=new URLSearchParams(location.search);if(data.samples[params.get('service')])service=params.get('service');if(['new','payment','rejected','review','working','done'].includes(params.get('state')))state=params.get('state');let initial=decodeURIComponent(location.hash.slice(1));show(data.cards[initial]||data.examples[initial.slice(2)]||(initial==='c:current'&&state)?initial:'c:home');
</script></body></html>'''


def main():
    destination = ROOT / "artifacts" / "ui-preview.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(export_cards(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    destination.write_text(HTML.replace("__DATA__", payload), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
