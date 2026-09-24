-- Keep only images that resolve inside the render directory.
--
-- mdd copies the page's own attachments directory next to the source it
-- renders, so a relative path such as "Page-attachments/image1.png" is all a
-- legitimate document needs. Any other target (a URL, an absolute path or a
-- path that climbs out with "..") is replaced by the image's alt text, and the
-- dropped target is reported on stderr.

local MAX_DECODE_PASSES = 8

-- Decode until nothing changes, so "%252e%252e" is seen as "..". Returns nil
-- when the target is still changing after MAX_DECODE_PASSES.
local function percent_decode(s)
  for _ = 1, MAX_DECODE_PASSES do
    local decoded = s:gsub("%%(%x%x)", function(h)
      return string.char(tonumber(h, 16))
    end)
    if decoded == s then
      return s
    end
    s = decoded
  end
  return nil
end

local function outside_render_dir(src)
  local s = percent_decode(src)
  if s == nil then
    return true
  end
  if s:match("^data:image/") then
    return false
  end
  if s:match("^%a[%w+.-]*:") then
    return true -- any URI scheme: http, https, file, ftp, a drive letter, ...
  end
  if s:match("^[/\\]") then
    return true -- absolute path, //host or \\host
  end
  if s:find("\\", 1, true) then
    return true
  end
  for segment in s:gmatch("[^/]+") do
    if segment == ".." then
      return true
    end
  end
  return false
end

local function printable(s)
  return (s:gsub("%c", function(c)
    return string.format("\\x%02x", c:byte())
  end))
end

local function report(src)
  io.stderr:write("mdd: dropped image outside the page's attachments: " .. printable(src) .. "\n")
end

function Image(el)
  if outside_render_dir(el.src) then
    report(el.src)
    return el.caption
  end
end

-- Attributes such as background-image on a slide heading also make the
-- writer embed a file, so they get the same check as image targets.
local function guard_attributes(el)
  local dropped = {}
  for key, value in pairs(el.attributes) do
    if key:lower():find("image", 1, true) and outside_render_dir(value) then
      report(value)
      table.insert(dropped, key)
    end
  end
  if #dropped == 0 then
    return nil
  end
  for _, key in ipairs(dropped) do
    el.attributes[key] = nil
  end
  return el
end

Header = guard_attributes
Div = guard_attributes
Span = guard_attributes
Figure = guard_attributes
Table = guard_attributes
