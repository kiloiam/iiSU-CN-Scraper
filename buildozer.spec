[app]
title = iiSU-CN-Scraper
package.name = iisucnscraper
package.domain = org.iisucn
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0.0
requirements = python3,kivy,requests
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE
android.api = 30
android.minapi = 26
android.ndk = 25b
android.archs = arm64-v8a
# p4a.branch = develop  # use stable default
p4a.bootstrap = sdl2
ios.kivy_ios_url = https://github.com/kivy/kivy-ios
ios.kivy_ios_branch = master
ios.codesign.allowed = false

[buildozer]
log_level = 2
warn_on_root = 1
