from flask import Flask, jsonify, render_template, request
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
import aiohttp
import asyncio

app = Flask(__name__)

# Bảng quy đổi Tiết học sang Giờ thực tế (Hãy điều chỉnh lại phút theo trường của bạn)
PERIOD_TIME_MAP = {
    1: ("07:00", "07:45"), 2: ("07:45", "08:30"), 3: ("08:30", "09:15"), 
    4: ("09:35", "10:20"), 5: ("10:20", "11:05"), 6: ("11:05", "11:50"),
    7: ("12:30", "13:15"), 8: ("13:15", "14:00"), 9: ("14:00", "14:45"), 
    10: ("15:00", "16:15"), 11: ("16:15", "17:00"), 12: ("17:00", "17:45")
}


# --- HÀM 1: ĐĂNG NHẬP VÀ LẤY HTML (TÍCH HỢP TỪ TEST_LOGIN) ---
async def fetch_html_async(username, password):
    # ==============================================================
    # BẠN HÃY THAY LẠI 2 ĐƯỜNG LINK NÀY GIỐNG NHƯ TRONG FILE TEST
    # ==============================================================
    login_url = "http://qldt.actvn.edu.vn/CMCSoft.IU.Web.Info/Login.aspx"
    tkb_url = "http://qldt.actvn.edu.vn/CMCSoft.IU.Web.Info/StudyRegister/StudyRegister.aspx"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            # 1. Lấy Token ẩn
            async with session.get(login_url) as init_res:
                if init_res.status != 200: return None
                soup = BeautifulSoup(await init_res.text(), 'html.parser')
                
                viewstate = soup.find('input', id='__VIEWSTATE')
                viewstate_gen = soup.find('input', id='__VIEWSTATEGENERATOR')
                event_validation = soup.find('input', id='__EVENTVALIDATION')
                
                lang_dropdown = soup.find('select', id='PageHeader1_drpNgonNgu')
                lang_value = lang_dropdown.find('option', selected=True)['value'] if lang_dropdown and lang_dropdown.find('option', selected=True) else 'E43296C6F24C4410A894F46D57D2D3AB'

            # 2. Gửi Payload Đăng nhập
            payload = {
                '__EVENTTARGET': '',
                '__EVENTARGUMENT': '',
                '__LASTFOCUS': '',
                '__VIEWSTATE': viewstate['value'] if viewstate else '',
                '__VIEWSTATEGENERATOR': viewstate_gen['value'] if viewstate_gen else '',
                '__EVENTVALIDATION': event_validation['value'] if event_validation else '',
                'PageHeader1$drpNgonNgu': lang_value,
                'PageHeader1$hidisNotify': '0',
                'PageHeader1$hidValueNotify': '.',
                'txtUserName': username,
                'txtPassword': password,
                'btnSubmit': 'Đăng nhập',
                'hidUserId': '',
                'hidUserFullName': ''
            }
            
            async with session.post(login_url, data=payload) as login_res:
                # Bỏ qua kiểm tra status vì có thể bị redirect (302) khi login thành công
                pass 
                
            # 3. Kéo dữ liệu TKB
            async with session.get(tkb_url) as tkb_res:
                if tkb_res.status == 200:
                    return await tkb_res.text()
                return None
        except Exception as e:
            print(f"Lỗi hệ thống mạng: {e}")
            return None

# --- HÀM 2: BÓC TÁCH DỮ LIỆU HTML THÀNH SỰ KIỆN CHO LỊCH ---
def parse_schedule_to_events(html_content):
    if not html_content:
        return []
        
    soup = BeautifulSoup(html_content, 'html.parser')
    events = []
    
    # Quét bắt đầu từ mã _0, _1, ...
    course_name_tags = soup.find_all('span', id=re.compile(r'^gridRegistered_lblCourseClass_\d+$'))
    
    for course_tag in course_name_tags:
        idx = course_tag['id'].split('_')[-1]
        
        course_code_tag = soup.find('span', id=f'gridRegistered_lblCourseCode_{idx}')
        time_location_tag = soup.find('span', id=f'gridRegistered_lblLongTime_{idx}')
        location_tag = soup.find('span', id=f'gridRegistered_lblLocation_{idx}')
        
        course_name = course_tag.text.strip()
        course_code = course_code_tag.text.strip() if course_code_tag else "Không có mã"
        room_name = location_tag.text.strip() if location_tag else "Chưa có phòng"
        
        if time_location_tag:
            raw_text = time_location_tag.get_text(separator="\n", strip=True).replace('\xa0', ' ')
            date_blocks = raw_text.split('Từ')
            
            for block in date_blocks:
                if 'đến' not in block: continue
                
                date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s*đến\s*(\d{2}/\d{2}/\d{4})', block)
                if not date_match: continue
                
                start_date_str, end_date_str = date_match.groups()
                start_date = datetime.strptime(start_date_str, "%d/%m/%Y")
                end_date = datetime.strptime(end_date_str, "%d/%m/%Y")
                
                schedule_matches = re.finditer(r'(Thứ\s+(\d)|Chủ Nhật)\s*tiết\s*([\d,]+)', block, re.IGNORECASE)
                
                for match in schedule_matches:
                    day_of_week = int(match.group(2)) - 2 if match.group(2) else 6
                    periods = [int(p) for p in match.group(3).split(',')]
                    
                    start_period = min(periods)
                    end_period = max(periods)
                    
                    current_date = start_date
                    while current_date <= end_date:
                        if current_date.weekday() == day_of_week:
                            date_str = current_date.strftime("%Y-%m-%d")
                            start_time_str = PERIOD_TIME_MAP.get(start_period, ("00:00", "00:00"))[0]
                            end_time_str = PERIOD_TIME_MAP.get(end_period, ("00:00", "23:59"))[1]
                            
                            events.append({
                                "title": course_name,
                                "start": f"{date_str}T{start_time_str}:00",
                                "end": f"{date_str}T{end_time_str}:00",
                                "extendedProps": {
                                    "room": room_name,
                                    "period": match.group(3),
                                    "code": course_code
                                }
                            })
                        current_date += timedelta(days=1)
                        
    return events


# ==============================================================================
# HÀM BỔ SUNG: CÀO BẢNG ĐIỂM KMA QUA MICROSOFT SSO
# ==============================================================================

# Hàm chuyên dụng để trích xuất Token từ JavaScript của Microsoft
def extract_token(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""

def parse_grades_from_soup(soup):
    """Trích xuất danh sách điểm từ BeautifulSoup của trang bảng điểm."""
    rows = soup.find_all('tr')
    mon_hoc_list = []

    for row in rows:
        cols = row.find_all('td')
        if len(cols) >= 12:
            stt = cols[0].text.strip()
            if stt.isdigit():
                def safe_float(val):
                    try: return float(val)
                    except ValueError: return val

                mon_hoc_list.append({
                    'stt': int(stt),
                    'nam_hoc': cols[2].text.strip(),
                    'hoc_ky': int(cols[3].text.strip()) if cols[3].text.strip().isdigit() else cols[3].text.strip(),
                    'ten_mon': cols[4].text.strip(),
                    'diem_qt': safe_float(cols[8].text.strip()),
                    'diem_ck': safe_float(cols[9].text.strip()),
                    'diem_hp': safe_float(cols[10].text.strip()),
                    'diem_chu': cols[11].text.strip()
                })
    return mon_hoc_list

async def fetch_kma_grades(username, password):
    # Cấu hình các đường link quan trọng
    INITIAL_LOGIN_URL = 'https://login.microsoftonline.com/0aa16d8a-a396-4e21-aa14-2a68a45786bc/oauth2/v2.0/authorize?response_type=code&client_id=fbad147e-ffd3-419f-989a-7aceae620f77&redirect_uri=https%3A%2F%2Fktdbcl.actvn.edu.vn%2Findex.php%2Faksociallogin_finishLogin%2Fmicrosoft.raw&scope=user.read&response_mode=query'
    GCT_URL = 'https://login.microsoftonline.com/common/GetCredentialType?mkt=en-US'
    POST_URL = 'https://login.microsoftonline.com/0aa16d8a-a396-4e21-aa14-2a68a45786bc/login'
    GRADE_URL = 'https://ktdbcl.actvn.edu.vn/khao-thi/hvsv/xem-diem-thi.html'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8'
    }

    async with aiohttp.ClientSession() as session:
        try:
            # [0] KHỞI TẠO PHIÊN VỚI TRƯỜNG ĐỂ NHẬN SESSION COOKIE JOOMLA
            try:
                async with session.get('https://ktdbcl.actvn.edu.vn/dang-nhap.html', headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as init_ktdbcl:
                    print(f"[DEBUG] Khởi tạo web trường status: {init_ktdbcl.status}")
            except Exception as e:
                print(f"[WARN] Không thể kết nối trước tới ktdbcl.actvn.edu.vn: {e}")

            # [1] LẤY TOKEN MỒI TỪ MICROSOFT
            async with session.get(INITIAL_LOGIN_URL, headers=headers) as res1:
                html1 = await res1.text()
                tokens = {
                    'flowToken': extract_token([r"""['"]sFT['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]flowToken['"]\s+value=['"]([^'"]+)['"]"""], html1),
                    'ctx': extract_token([r"""['"]sCtx['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]ctx['"]\s+value=['"]([^'"]+)['"]"""], html1),
                    'canary': extract_token([r"""['"]canary['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]canary['"]\s+value=['"]([^'"]+)['"]"""], html1),
                    'hpgrequestid': extract_token([r"""['"]sessionId['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]hpgrequestid['"]\s+value=['"]([^'"]+)['"]"""], html1)
                }
                if not tokens['flowToken']:
                    print("[ERROR] Không lấy được flowToken từ Microsoft")
                    return {"status": "error", "message": "Không lấy được Token khởi tạo từ hệ thống Microsoft."}

            # [2] XÁC THỰC USERNAME
            gct_payload = {
                "checkPhones": True, "country": "VN", "federationFlags": 0, "flowToken": tokens['flowToken'], 
                "forceotclogin": False, "isAccessPassSupported": True, "isCookieBannerShown": False,
                "isExternalFederationDisallowed": False, "isFidoSupported": True, "isOtherIdpSupported": True,
                "isQrCodePinSupported": True, "isRemoteConnectSupported": False, "isRemoteNGCSupported": True,
                "isSignup": False, "originalRequest": tokens['ctx'], "username": username              
            }
            headers_json = headers.copy()
            headers_json['Content-Type'] = 'application/json; charset=UTF-8'
            
            async with session.post(GCT_URL, json=gct_payload, headers=headers_json) as gct_res:
                gct_data = await gct_res.json()
                if 'FlowToken' in gct_data:
                    tokens['flowToken'] = gct_data['FlowToken']
                elif 'EstsAuth' in gct_data.get('Credentials', {}):
                    tokens['flowToken'] = gct_data['Credentials']['EstsAuth']
                else:
                    return {"status": "error", "message": "Sai tài khoản hoặc máy chủ Microsoft từ chối yêu cầu."}

            # [3] GỬI PASSWORD & XỬ LÝ SSO REDIRECTS
            login_payload = {
                'login': username, 'loginfmt': username, 'type': '11', 'LoginOptions': '3',
                'lrt': '', 'lrtPartition': '', 'hisRegion': '', 'hisScaleUnit': '',
                'passwd': password, 'ps': '2', 'psRNGCDefaultType': '', 'psRNGCEntropy': '', 'psRNGCSLK': '',
                'canary': tokens['canary'], 'ctx': tokens['ctx'], 'hpgrequestid': tokens['hpgrequestid'],
                'flowToken': tokens['flowToken']
            }
            headers_form = headers.copy()
            headers_form['Content-Type'] = 'application/x-www-form-urlencoded'
            
            callback_url = ""

            async with session.post(POST_URL, data=login_payload, headers=headers_form, allow_redirects=False) as login_res:
                print(f"[DEBUG] POST login status: {login_res.status}")
                if login_res.status in (302, 303):
                    callback_url = login_res.headers.get('Location')
                elif login_res.status == 200:
                    login_html = await login_res.text()
                    soup = BeautifulSoup(login_html, 'html.parser')
                    form = soup.find('form')
                    
                    if form:
                        action_url = form.get('action')
                        if not action_url.startswith('http'): action_url = "https://login.microsoftonline.com" + action_url
                        form_payload = {i.get('name'): i.get('value', '') for i in form.find_all('input') if i.get('name')}
                        
                        if "kmsi" in action_url.lower() or "login" in action_url.lower():
                            form_payload.update({'LoginOptions': '1', 'type': '28', 'DontShowAgain': 'true', 'i19': '38600'})
                            
                        async with session.post(action_url, data=form_payload, headers=headers_form, allow_redirects=False) as form_res:
                            print(f"[DEBUG] Form KMSI status: {form_res.status}")
                            if form_res.status in (302, 303):
                                callback_url = form_res.headers.get('Location')
                            elif form_res.status == 200:
                                kmsi_html = await form_res.text()
                                code_match = re.search(r"""(https://[^'"]*actvn\.edu\.vn[^'"]*[?&]code=[^'"]+)""", kmsi_html)
                                if code_match:
                                    callback_url = code_match.group(1).replace(r'\/', '/').replace(r'\u0026', '&')
                    
                    if not callback_url and ("sso_reload" in login_html or "window.location" in login_html):
                        all_urls = re.findall(r"""['"]([^'"]*?sso_reload[^'"]*?)['"]""", login_html, re.IGNORECASE)
                        if all_urls:
                            redirect_url = all_urls[0].replace(r'\/', '/').encode('utf-8').decode('unicode_escape')
                            if redirect_url.startswith('/'): redirect_url = "https://login.microsoftonline.com" + redirect_url
                                
                            async with session.post(redirect_url, data=login_payload, headers=headers_form, allow_redirects=False) as sso_res:
                                print(f"[DEBUG] sso_reload status: {sso_res.status}")
                                if sso_res.status in (302, 303):
                                    callback_url = sso_res.headers.get('Location')
                                elif sso_res.status == 200:
                                    sso_html = await sso_res.text()
                                    soup2 = BeautifulSoup(sso_html, 'html.parser')
                                    form2 = soup2.find('form')
                                    if form2 and form2.get('action'):
                                        action_url2 = form2.get('action')
                                        form_payload2 = {i.get('name'): i.get('value', '') for i in form2.find_all('input') if i.get('name')}
                                    else:
                                        url_post_match = re.search(r"""urlPost['"]?\s*:\s*['"]([^'"]+)['"]""", sso_html)
                                        action_url2 = url_post_match.group(1) if url_post_match else "/common/kmsi"
                                        if not action_url2.startswith('http'): action_url2 = "https://login.microsoftonline.com" + action_url2
                                            
                                        form_payload2 = {
                                            'LoginOptions': '1', 'type': '28', 'i19': '2582',
                                            'ctx': extract_token([r"""['"]sCtx['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]ctx['"]\s+value=['"]([^'"]+)['"]"""], sso_html),
                                            'hpgrequestid': extract_token([r"""['"]sessionId['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]hpgrequestid['"]\s+value=['"]([^'"]+)['"]"""], sso_html),
                                            'flowToken': extract_token([r"""['"]sFT['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]flowToken['"]\s+value=['"]([^'"]+)['"]"""], sso_html),
                                            'canary': extract_token([r"""['"]canary['"]\s*:\s*['"]([^'"]+)['"]""", r"""name=['"]canary['"]\s+value=['"]([^'"]+)['"]"""], sso_html)
                                        }
                                    
                                    async with session.post(action_url2, data=form_payload2, headers=headers_form, allow_redirects=False) as form_res2:
                                        print(f"[DEBUG] form_res2 status: {form_res2.status}")
                                        if form_res2.status in (302, 303):
                                            callback_url = form_res2.headers.get('Location')
                                        elif form_res2.status == 200:
                                            kmsi_html = await form_res2.text()
                                            redirect_url = None
                                            all_urls = re.findall(r"""['"]([^'"]*?sso_reload[^'"]*?)['"]""", kmsi_html, re.IGNORECASE)
                                            if all_urls: redirect_url = all_urls[0].replace(r'\/', '/')
                                            elif "?sso_reload=true" in kmsi_html: redirect_url = str(form_res2.url) + "?sso_reload=true"
                                            
                                            if redirect_url:
                                                redirect_url = redirect_url.encode('utf-8').decode('unicode_escape')
                                                if redirect_url.startswith('/'): redirect_url = "https://login.microsoftonline.com" + redirect_url
                                                async with session.post(redirect_url, data=form_payload2, headers=headers_form, allow_redirects=False) as final_hop:
                                                    print(f"[DEBUG] final_hop status: {final_hop.status}")
                                                    if final_hop.status in (302, 303): callback_url = final_hop.headers.get('Location')
                                                    elif final_hop.status == 200:
                                                        final_html = await final_hop.text()
                                                        code_match = re.search(r"""(https://[^'"]*actvn\.edu\.vn[^'"]*[?&]code=[^'"]+)""", final_html)
                                                        if code_match: callback_url = code_match.group(1).replace(r'\/', '/').replace(r'\u0026', '&')

            print(f"[DEBUG] callback_url: {callback_url}")

            # [4] XỬ LÝ VÀ NỘP MÃ XÁC THỰC CHO TRƯỜNG
            if not callback_url or 'actvn.edu.vn' not in callback_url:
                return {"status": "error", "message": "Sai mật khẩu hoặc tài khoản bị Microsoft chặn đăng nhập tự động."}

            # Kiểm tra xem Microsoft có trả về lỗi OAuth hay không
            if 'error=' in callback_url:
                import urllib.parse
                parsed = urllib.parse.urlparse(callback_url)
                params = urllib.parse.parse_qs(parsed.query)
                err_code = params.get('error', ['unknown'])[0]
                err_desc = params.get('error_description', [''])[0]
                print(f"[ERROR] Microsoft OAuth Error: {err_code} - {err_desc}")

                if 'AADSTS50076' in err_desc or 'AADSTS50079' in err_desc:
                    return {"status": "error", "message": "Tài khoản yêu cầu Xác thực 2 bước (MFA). Vui lòng đăng nhập trên trình duyệt trước."}
                if 'AADSTS53003' in err_desc:
                    return {"status": "error", "message": "Microsoft chặn truy cập do chính sách vị trí/IP máy chủ (Conditional Access)."}
                return {"status": "error", "message": f"Microsoft từ chối đăng nhập: {err_desc or err_code}"}

            if 'code=' not in callback_url:
                return {"status": "error", "message": "Microsoft không trả về mã xác thực (Authorization Code)."}

            async with session.get(callback_url, headers=headers, allow_redirects=True) as final_auth_res:
                print(f"[DEBUG] final_auth_res status: {final_auth_res.status}, url: {final_auth_res.url}")

            # [5] TRUY CẬP TRANG ĐÍCH VÀ ÉP HIỂN THỊ TẤT CẢ
            async with session.get(GRADE_URL, headers=headers, allow_redirects=True) as grade_res:
                print(f"[DEBUG] grade_res status: {grade_res.status}, url: {grade_res.url}")
                html_content = await grade_res.text()

            if grade_res.status == 404:
                return {
                    "status": "error",
                    "message": "Không tìm thấy trang bảng điểm (HTTP 404). Phiên đăng nhập chưa được trường xác thực hoặc tài khoản chưa được phân quyền xem điểm."
                }
            if "dang-nhap" in str(grade_res.url) or "login" in str(grade_res.url):
                return {
                    "status": "error",
                    "message": "Hệ thống bị chuyển hướng về trang đăng nhập của trường. Xác thực tài khoản chưa thành công."
                }

            soup_diem = BeautifulSoup(html_content, 'html.parser')

            # Thử bóc tách trực tiếp nếu bảng điểm đã hiển thị sẵn mà không cần bấm nút phân trang
            initial_grades = parse_grades_from_soup(soup_diem)

            # Tìm Form phân trang (nếu có) để tải trọn vẹn tất cả các môn
            form_list = soup_diem.find('form', id='adminForm')
            if not form_list:
                form_list = soup_diem.find(lambda tag: tag.name == 'form' and tag.find('input', {'name': 'list[limit]'}))

            if form_list:
                full_payload = {i.get('name'): i.get('value', '') for i in form_list.find_all(['input', 'select']) if i.get('name')}
                full_payload['list[limit]'] = '0'
                full_payload['limitstart'] = '0'
                
                from urllib.parse import urljoin
                form_action = form_list.get('action') or GRADE_URL
                if not form_action.startswith('http'): form_action = urljoin(GRADE_URL, form_action)
            
                async with session.post(form_action, data=full_payload, headers=headers) as full_res:
                    if full_res.status == 200:
                        full_html = await full_res.text()
                        soup_full = BeautifulSoup(full_html, 'html.parser')
                        grades = parse_grades_from_soup(soup_full)
                        if grades:
                            return {"status": "success", "data": grades}
            
            # Nếu không có form phân trang hoặc post form không trả về data nhưng trang ban đầu đã có điểm
            if initial_grades:
                return {"status": "success", "data": initial_grades}

            # Kiểm tra xem có thông báo không có điểm hay không
            alert_box = soup_diem.find(class_=re.compile(r'alert|message', re.IGNORECASE))
            if alert_box and alert_box.text.strip():
                return {"status": "error", "message": f"Thông báo từ hệ thống trường: {alert_box.text.strip()}"}

            return {"status": "error", "message": "Không tìm thấy dữ liệu bảng điểm trên trang web của trường."}
                
        except Exception as e:
            print(f"[ERROR] fetch_kma_grades exception: {e}")
            return {"status": "error", "message": f"Lỗi hệ thống: {str(e)}"}



# --- ROUTING FLASK ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/schedule', methods=['POST'])
def get_schedule():
    # Frontend gửi user/pass lên qua chuẩn JSON
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"error": "Vui lòng nhập đầy đủ Tài khoản và Mật khẩu!"}), 400

    # Khởi chạy hàm cào dữ liệu bất đồng bộ
    try:
        html_content = asyncio.run(fetch_html_async(username,password))
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": f"Server error: {e}"}), 500
    
    if html_content:
        events = parse_schedule_to_events(html_content)
        if len(events) == 0:
            return jsonify({"error": "Đăng nhập thành công nhưng không tìm thấy dữ liệu Thời khóa biểu!"}), 404
        return jsonify(events)
    else:
        return jsonify({"error": "Sai tài khoản, mật khẩu hoặc Server trường đang bảo trì!"}), 401


@app.route('/api/get_grades', methods=['POST'])
def api_get_grades():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"status": "error", "message": "Thiếu tài khoản hoặc mật khẩu"}), 400
        
    # Gọi hàm async trong môi trường đồng bộ của Flask
    result = asyncio.run(fetch_kma_grades(username, password))
    
    return jsonify(result)


if __name__ == '__main__':
    app.run(debug=True, host= '0.0.0.0',port=5000)