script_name("RealtorParser")
script_author("RealtorTeam")
script_version("6.3")

local sampevents = require("lib.samp.events")
local requests = require("requests")

local encoding = require("encoding")
encoding.default = "CP1251"
local u8 = encoding.UTF8

-- ВСТАВЬ СВОЮ ССЫЛКУ ИЗ RENDER
local CLOUD_URL = "https://arizona-rec.onrender.com/api/update"

local current_server_cached = nil
local current_season = "Неизвестно"

local SERVERS_DB = {
    { id = "01", name = "Phoenix",     ip = "185.169.134.3",   key = "phoenix" },
    { id = "02", name = "Tucson",      ip = "185.169.134.4",   key = "tucson" },
    { id = "03", name = "Scottdale",   ip = "185.169.134.43",  key = "scottdale" },
    { id = "04", name = "Chandler",    ip = "185.169.134.44",  key = "chandler" },
    { id = "05", name = "Brainburg",   ip = "185.169.134.45",  key = "brainburg" },
    { id = "06", name = "Saint-Rose",  ip = "185.169.134.5",   key = "saint" },
    { id = "07", name = "Mesa",        ip = "185.169.134.59",  key = "mesa" },
    { id = "08", name = "Red-Rock",    ip = "185.169.134.61",  key = "red" },
    { id = "09", name = "Yuma",        ip = "185.169.134.107", key = "yuma" },
    { id = "10", name = "Surprise",    ip = "185.169.134.109", key = "surprise" },
    { id = "11", name = "Prescott",    ip = "185.169.134.166", key = "prescott" },
    { id = "12", name = "Glendale",    ip = "185.169.134.171", key = "glendale" },
    { id = "13", name = "Kingman",     ip = "185.169.134.172", key = "kingman" },
    { id = "14", name = "Winslow",     ip = "185.169.134.173", key = "winslow" },
    { id = "15", name = "Payson",      ip = "185.169.134.174", key = "payson" },
    { id = "16", name = "Gilbert",     ip = "80.66.82.191",    key = "gilbert" },
    { id = "17", name = "Show-Low",    ip = "80.66.82.190",    key = "show" },
    { id = "18", name = "Casa-Grande", ip = "80.66.82.188",    key = "casa" },
    { id = "19", name = "Page",        ip = "80.66.82.168",    key = "page" },
    { id = "20", name = "Sun-City",    ip = "80.66.82.159",    key = "sun" },
    { id = "21", name = "Queen-Creek", ip = "80.66.82.200",    key = "queen" },
    { id = "22", name = "Sedona",      ip = "80.66.82.144",    key = "sedona" },
    { id = "23", name = "Holiday",     ip = "80.66.82.132",    key = "holiday" },
    { id = "24", name = "Wednesday",   ip = "80.66.82.128",    key = "wednesday" },
    { id = "25", name = "Yava",        ip = "80.66.82.113",    key = "yava" },
    { id = "26", name = "Faraway",     ip = "80.66.82.82",     key = "faraway" },
    { id = "27", name = "Bumble Bee",  ip = "80.66.82.87",     key = "bumble" },
    { id = "28", name = "Christmas",   ip = "80.66.82.54",     key = "christmas" },
    { id = "29", name = "Mirage",      ip = "80.66.82.39",     key = "mirage" },
    { id = "30", name = "Love",        ip = "80.66.82.33",     key = "love" },
    { id = "31", name = "Drake",       ip = "80.66.82.22",     key = "drake" },
    { id = "32", name = "Space",       ip = "80.66.82.199",    key = "space" },
    { id = "33", name = "Home",        ip = "80.66.82.235",    key = "home" }
}

function main()
    if not isSampLoaded() or not isSampfuncsLoaded() then return end
    while not isSampAvailable() do wait(100) end
    current_server_cached = get_current_server_info()
    sampAddChatMessage(u8:decode("{00FF00}[RealtorParser v6.3]{FFFFFF} Запущен!"), -1)
    while true do wait(1000) end
end

function get_current_server_info()
    if current_server_cached and current_server_cached.id ~= "??" then return current_server_cached end
    local ip, port = sampGetCurrentServerAddress()
    local sname = sampGetCurrentServerName() or ""
    local ip_str, sname_str = tostring(ip):lower(), tostring(sname):lower()
    for _, item in ipairs(SERVERS_DB) do
        if ip_str == item.ip or ip_str:find(item.key, 1, true) or sname_str:find(item.key, 1, true) then
            return { id = item.id, name = item.name }
        end
    end
    return { id = "??", name = string.format("Unknown (%s)", ip) }
end

function sampevents.onServerMessage(color, text)
    if not text then return end
    local clean = text:gsub("{%x%x%x%x%x%x}", "")
    local utf8_text = u8(clean)
    if not utf8_text then return end

    local s_name = utf8_text:match("активен сезон%s*%-%s*['\"](.-)['\"]") or utf8_text:match("активен сезон%s*%-%s*(.-)!")
    if s_name then
        current_season = s_name:gsub("^%s+", ""):gsub("%s+$", ""):gsub("['\"]", "")
        sampAddChatMessage(u8:decode(string.format("{00FF00}[RealtorParser]{FFFFFF} Сезон: {FFD700}%s", current_season)), -1)
    end
end

function sampevents.onShowDialog(dialogId, style, title, button1, button2, text)
    if dialogId ~= 26138 and dialogId ~= 26136 and dialogId ~= 26788 then return end

    local server_info = get_current_server_info()
    local parsed_items = parse_realtor_text(text)
    
    if #parsed_items == 0 then return end

    sampAddChatMessage(u8:decode(string.format("{00FF00}[RealtorParser]{FFFFFF} Считано объектов: %d", #parsed_items)), -1)
    for _, item in ipairs(parsed_items) do
        sampAddChatMessage(u8:decode(string.format("{FFD700}Pos №%d{FFFFFF}: %s | %d PD", item.slot, item.type, item.payday)), -1)
    end

    send_to_cloud(server_info, parsed_items)
end

function send_to_cloud(server_info, items)
    lua_thread.create(function()
        sampAddChatMessage(u8:decode("{FFFF00}[Tracker]{FFFFFF} Синхронизация с облаком..."), -1)
        
        local payload = {
            server_id = server_info.id,
            server_name = server_info.name,
            season = current_season,
            scan_ts = os.time(),
            items = items
        }
        
        local status, response = pcall(requests.post, CLOUD_URL, {
            headers = { ["Content-Type"] = "application/json" },
            data = encodeJson(payload),
            timeout = 15
        })
        
        if status and response and response.status_code == 200 then
            sampAddChatMessage(u8:decode("{00FF00}[Tracker]{FFFFFF} Данные успешно синхронизированы!"), -1)
        else
            local err_code = response and tostring(response.status_code) or "ошибка сети"
            sampAddChatMessage(u8:decode("{FF0000}[Tracker] Ошибка связи: " .. err_code), -1)
        end
    end)
end

function parse_realtor_text(text)
    local items = {}
    local clean = text:gsub("{.-}", "")
    local biz_kw = u8:decode("Бизнес")
    
    for line in clean:gmatch("[^\r\n]+") do
        -- Универсальный паттерн для поиска слота и количества PayDay (поддерживает формат диалога бизнесов и домов)
        local p, pd = line:match("^%s*(%d+)%s*%.?%s*.-(%d+)%s*[Pp]ay[Dd]ay")
        if not p or not pd then
            -- Запасной вариант для коротких строк вроде "1 | ID: Неизвестно Слетится через: 4 Payday"
            p, pd = line:match("(%d+)%s*|.-(%d+)%s*[Pp]ay[Dd]ay")
        end
        if not p or not pd then
            -- Вариант, если вместо слова PayDay написано просто число в конце или PD
            p, pd = line:match("(%d+)%D+(%d+)%s*([Pp][Dd])?")
        end

        if p and pd then
            local obj_type = "Дом"
            if line:find(biz_kw, 1, true) or line:lower():find("biz", 1, true) or line:lower():find("бизнес", 1, true) then
                obj_type = "Бизнес"
            end
            table.insert(items, {
                slot = tonumber(p),
                payday = tonumber(pd),
                type = obj_type
            })
        end
    end
    return items
end
