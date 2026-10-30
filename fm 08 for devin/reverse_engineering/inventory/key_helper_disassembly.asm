
; indexed_table_accessor at 0xc933f0
Disassembly of section .text:

00c933f0 <.text+0x8923f0>:
  c933f0:	a1 cc f0 b1 01       	mov    eax,ds:0x1b1f0cc
  c933f5:	56                   	push   esi
  c933f6:	8b 74 24 08          	mov    esi,DWORD PTR [esp+0x8]
  c933fa:	57                   	push   edi
  c933fb:	33 ff                	xor    edi,edi
  c933fd:	3b f0                	cmp    esi,eax
  c933ff:	7c 45                	jl     0xc93446
  c93401:	8b 0d c8 f0 b1 01    	mov    ecx,DWORD PTR ds:0x1b1f0c8
  c93407:	8d 04 b5 04 00 00 00 	lea    eax,[esi*4+0x4]
  c9340e:	50                   	push   eax
  c9340f:	51                   	push   ecx
  c93410:	8b 0d 84 05 b2 01    	mov    ecx,DWORD PTR ds:0x1b20584
  c93416:	e8 85 45 2b 00       	call   0xf479a0
  c9341b:	a3 c8 f0 b1 01       	mov    ds:0x1b1f0c8,eax
  c93420:	a1 cc f0 b1 01       	mov    eax,ds:0x1b1f0cc
  c93425:	3b c6                	cmp    eax,esi
  c93427:	7f 15                	jg     0xc9343e
  c93429:	8d a4 24 00 00 00 00 	lea    esp,[esp+0x0]
  c93430:	8b 15 c8 f0 b1 01    	mov    edx,DWORD PTR ds:0x1b1f0c8
  c93436:	89 3c 82             	mov    DWORD PTR [edx+eax*4],edi
  c93439:	40                   	inc    eax
  c9343a:	3b c6                	cmp    eax,esi
  c9343c:	7e f2                	jle    0xc93430
  c9343e:	8d 46 01             	lea    eax,[esi+0x1]
  c93441:	a3 cc f0 b1 01       	mov    ds:0x1b1f0cc,eax
  c93446:	8b 0d c8 f0 b1 01    	mov    ecx,DWORD PTR ds:0x1b1f0c8
  c9344c:	39 3c b1             	cmp    DWORD PTR [ecx+esi*4],edi
  c9344f:	75 4d                	jne    0xc9349e
  c93451:	6a 28                	push   0x28
  c93453:	e8 88 45 2b 00       	call   0xf479e0
  c93458:	83 c4 04             	add    esp,0x4
  c9345b:	3b c7                	cmp    eax,edi
  c9345d:	74 11                	je     0xc93470
  c9345f:	89 78 04             	mov    DWORD PTR [eax+0x4],edi
  c93462:	89 78 08             	mov    DWORD PTR [eax+0x8],edi
  c93465:	c7 00 8c f6 59 01    	mov    DWORD PTR [eax],0x159f68c
  c9346b:	89 78 0c             	mov    DWORD PTR [eax+0xc],edi
  c9346e:	eb 02                	jmp    0xc93472
  c93470:	33 c0                	xor    eax,eax
  c93472:	8b 15 c8 f0 b1 01    	mov    edx,DWORD PTR ds:0x1b1f0c8
  c93478:	89 04 b2             	mov    DWORD PTR [edx+esi*4],eax
  c9347b:	a1 c8 f0 b1 01       	mov    eax,ds:0x1b1f0c8
  c93480:	8b 0c b0             	mov    ecx,DWORD PTR [eax+esi*4]
  c93483:	b8 00 40 00 00       	mov    eax,0x4000
  c93488:	33 d2                	xor    edx,edx
  c9348a:	f7 f6                	div    esi
  c9348c:	89 71 14             	mov    DWORD PTR [ecx+0x14],esi
  c9348f:	89 79 20             	mov    DWORD PTR [ecx+0x20],edi
  c93492:	89 79 18             	mov    DWORD PTR [ecx+0x18],edi
  c93495:	89 79 1c             	mov    DWORD PTR [ecx+0x1c],edi
  c93498:	89 79 24             	mov    DWORD PTR [ecx+0x24],edi
  c9349b:	89 41 10             	mov    DWORD PTR [ecx+0x10],eax
  c9349e:	8b 0d c8 f0 b1 01    	mov    ecx,DWORD PTR ds:0x1b1f0c8
  c934a4:	8b 34 b1             	mov    esi,DWORD PTR [ecx+esi*4]
  c934a7:	39 7e 18             	cmp    DWORD PTR [esi+0x18],edi
  c934aa:	75 2b                	jne    0xc934d7
  c934ac:	8b 56 14             	mov    edx,DWORD PTR [esi+0x14]
  c934af:	0f af 56 10          	imul   edx,DWORD PTR [esi+0x10]
  c934b3:	52                   	push   edx
  c934b4:	e8 27 45 2b 00       	call   0xf479e0
  c934b9:	83 c4 04             	add    esp,0x4
  c934bc:	8d 4c 24 0c          	lea    ecx,[esp+0xc]
  c934c0:	89 44 24 0c          	mov    DWORD PTR [esp+0xc],eax
  c934c4:	8b 06                	mov    eax,DWORD PTR [esi]
  c934c6:	51                   	push   ecx
  c934c7:	8b ce                	mov    ecx,esi
  c934c9:	ff 10                	call   DWORD PTR [eax]
  c934cb:	8b 54 24 0c          	mov    edx,DWORD PTR [esp+0xc]
  c934cf:	52                   	push   edx
  c934d0:	8b ce                	mov    ecx,esi
  c934d2:	e8 c9 e8 ff ff       	call   0xc91da0
  c934d7:	8b 46 18             	mov    eax,DWORD PTR [esi+0x18]
  c934da:	3b c7                	cmp    eax,edi
  c934dc:	74 17                	je     0xc934f5
  c934de:	8b 48 04             	mov    ecx,DWORD PTR [eax+0x4]
  c934e1:	8b 56 1c             	mov    edx,DWORD PTR [esi+0x1c]
  c934e4:	89 4e 18             	mov    DWORD PTR [esi+0x18],ecx
  c934e7:	8b 4e 20             	mov    ecx,DWORD PTR [esi+0x20]
  c934ea:	4a                   	dec    edx
  c934eb:	41                   	inc    ecx
  c934ec:	5f                   	pop    edi
  c934ed:	89 56 1c             	mov    DWORD PTR [esi+0x1c],edx
  c934f0:	89 4e 20             	mov    DWORD PTR [esi+0x20],ecx
  c934f3:	5e                   	pop    esi
  c934f4:	c3                   	ret
  c934f5:	5f                   	pop    edi
  c934f6:	33 c0                	xor    eax,eax
  c934f8:	5e                   	pop    esi
  c934f9:	c3                   	ret
  c934fa:	cc                   	int3
  c934fb:	cc                   	int3
  c934fc:	cc                   	int3
  c934fd:	cc                   	int3
  c934fe:	cc                   	int3
  c934ff:	cc                   	int3

; shared_entry_update at 0xd35180
Disassembly of section .text:

00d35180 <.text+0x934180>:
  d35180:	51                   	push   ecx
  d35181:	53                   	push   ebx
  d35182:	55                   	push   ebp
  d35183:	8b 6c 24 18          	mov    ebp,DWORD PTR [esp+0x18]
  d35187:	56                   	push   esi
  d35188:	57                   	push   edi
  d35189:	8b 7c 24 24          	mov    edi,DWORD PTR [esp+0x24]
  d3518d:	66 83 ff fe          	cmp    di,0xfffe
  d35191:	89 4c 24 10          	mov    DWORD PTR [esp+0x10],ecx
  d35195:	75 04                	jne    0xd3519b
  d35197:	8b fd                	mov    edi,ebp
  d35199:	eb 09                	jmp    0xd351a4
  d3519b:	66 83 ff ff          	cmp    di,0xffff
  d3519f:	75 03                	jne    0xd351a4
  d351a1:	83 cf ff             	or     edi,0xffffffff
  d351a4:	8b 5c 24 18          	mov    ebx,DWORD PTR [esp+0x18]
  d351a8:	53                   	push   ebx
  d351a9:	b9 d0 ec b1 01       	mov    ecx,0x1b1ecd0
  d351ae:	e8 4d c3 ee ff       	call   0xc21500
  d351b3:	8b f0                	mov    esi,eax
  d351b5:	8b 44 24 1c          	mov    eax,DWORD PTR [esp+0x1c]
  d351b9:	50                   	push   eax
  d351ba:	b9 d0 ec b1 01       	mov    ecx,0x1b1ecd0
  d351bf:	e8 5c c3 ee ff       	call   0xc21520
  d351c4:	85 c0                	test   eax,eax
  d351c6:	75 03                	jne    0xd351cb
  d351c8:	8b 46 64             	mov    eax,DWORD PTR [esi+0x64]
  d351cb:	81 fb b8 db 13 00    	cmp    ebx,0x13dbb8
  d351d1:	74 15                	je     0xd351e8
  d351d3:	85 f6                	test   esi,esi
  d351d5:	74 52                	je     0xd35229
  d351d7:	8b 76 18             	mov    esi,DWORD PTR [esi+0x18]
  d351da:	8b 5c 24 10          	mov    ebx,DWORD PTR [esp+0x10]
  d351de:	8b 13                	mov    edx,DWORD PTR [ebx]
  d351e0:	56                   	push   esi
  d351e1:	8b cb                	mov    ecx,ebx
  d351e3:	ff 52 20             	call   DWORD PTR [edx+0x20]
  d351e6:	eb 19                	jmp    0xd35201
  d351e8:	85 c0                	test   eax,eax
  d351ea:	74 3d                	je     0xd35229
  d351ec:	8b 4c 24 10          	mov    ecx,DWORD PTR [esp+0x10]
  d351f0:	8b 40 18             	mov    eax,DWORD PTR [eax+0x18]
  d351f3:	8b 51 0c             	mov    edx,DWORD PTR [ecx+0xc]
  d351f6:	83 c1 0c             	add    ecx,0xc
  d351f9:	50                   	push   eax
  d351fa:	ff 52 20             	call   DWORD PTR [edx+0x20]
  d351fd:	8b 5c 24 10          	mov    ebx,DWORD PTR [esp+0x10]
  d35201:	8a 4c 24 2c          	mov    cl,BYTE PTR [esp+0x2c]
  d35205:	84 c9                	test   cl,cl
  d35207:	74 28                	je     0xd35231
  d35209:	66 89 68 04          	mov    WORD PTR [eax+0x4],bp
  d3520d:	66 89 78 06          	mov    WORD PTR [eax+0x6],di
  d35211:	66 8b 40 0a          	mov    ax,WORD PTR [eax+0xa]
  d35215:	66 3b c5             	cmp    ax,bp
  d35218:	7c 0b                	jl     0xd35225
  d3521a:	66 3b c7             	cmp    ax,di
  d3521d:	7e 0a                	jle    0xd35229
  d3521f:	66 83 ff ff          	cmp    di,0xffff
  d35223:	74 04                	je     0xd35229
  d35225:	c6 43 29 01          	mov    BYTE PTR [ebx+0x29],0x1
  d35229:	5f                   	pop    edi
  d3522a:	5e                   	pop    esi
  d3522b:	5d                   	pop    ebp
  d3522c:	5b                   	pop    ebx
  d3522d:	59                   	pop    ecx
  d3522e:	c2 18 00             	ret    0x18
  d35231:	66 83 78 04 00       	cmp    WORD PTR [eax+0x4],0x0
  d35236:	66 89 28             	mov    WORD PTR [eax],bp
  d35239:	66 89 78 02          	mov    WORD PTR [eax+0x2],di
  d3523d:	75 04                	jne    0xd35243
  d3523f:	66 89 68 04          	mov    WORD PTR [eax+0x4],bp
  d35243:	66 83 78 06 00       	cmp    WORD PTR [eax+0x6],0x0
  d35248:	75 04                	jne    0xd3524e
  d3524a:	66 89 78 06          	mov    WORD PTR [eax+0x6],di
  d3524e:	8a 48 10             	mov    cl,BYTE PTR [eax+0x10]
  d35251:	84 c9                	test   cl,cl
  d35253:	75 07                	jne    0xd3525c
  d35255:	8a 4c 24 28          	mov    cl,BYTE PTR [esp+0x28]
  d35259:	88 48 10             	mov    BYTE PTR [eax+0x10],cl
  d3525c:	66 39 68 08          	cmp    WORD PTR [eax+0x8],bp
  d35260:	b2 01                	mov    dl,0x1
  d35262:	7d 03                	jge    0xd35267
  d35264:	88 53 29             	mov    BYTE PTR [ebx+0x29],dl
  d35267:	66 8b 48 02          	mov    cx,WORD PTR [eax+0x2]
  d3526b:	66 83 f9 ff          	cmp    cx,0xffff
  d3526f:	7e b8                	jle    0xd35229
  d35271:	66 39 48 08          	cmp    WORD PTR [eax+0x8],cx
  d35275:	7e b2                	jle    0xd35229
  d35277:	5f                   	pop    edi
  d35278:	5e                   	pop    esi
  d35279:	5d                   	pop    ebp
  d3527a:	88 53 29             	mov    BYTE PTR [ebx+0x29],dl
  d3527d:	5b                   	pop    ebx
  d3527e:	59                   	pop    ecx
  d3527f:	c2 18 00             	ret    0x18

; allocation_retry_path at 0xf479e0
Disassembly of section .text:

00f479e0 <.text+0xb469e0>:
  f479e0:	56                   	push   esi
  f479e1:	8b 74 24 08          	mov    esi,DWORD PTR [esp+0x8]
  f479e5:	57                   	push   edi
  f479e6:	8b 3d 84 05 b2 01    	mov    edi,DWORD PTR ds:0x1b20584
  f479ec:	8d 64 24 00          	lea    esp,[esp+0x0]
  f479f0:	56                   	push   esi
  f479f1:	e8 dc 8a 1e 00       	call   0x11304d2
  f479f6:	83 c4 04             	add    esp,0x4
  f479f9:	85 c0                	test   eax,eax
  f479fb:	75 0d                	jne    0xf47a0a
  f479fd:	85 f6                	test   esi,esi
  f479ff:	74 09                	je     0xf47a0a
  f47a01:	8b cf                	mov    ecx,edi
  f47a03:	e8 78 fd ff ff       	call   0xf47780
  f47a08:	eb e6                	jmp    0xf479f0
  f47a0a:	5f                   	pop    edi
  f47a0b:	5e                   	pop    esi
  f47a0c:	c3                   	ret

; eng_discipline_rules at 0xf01fd0
Disassembly of section .text:

00f01fd0 <.text+0xb00fd0>:
  f01fd0:	56                   	push   esi
  f01fd1:	8b 74 24 0c          	mov    esi,DWORD PTR [esp+0xc]
  f01fd5:	6a ff                	push   0xffffffff
  f01fd7:	6a 01                	push   0x1
  f01fd9:	6a 0a                	push   0xa
  f01fdb:	6a 00                	push   0x0
  f01fdd:	56                   	push   esi
  f01fde:	e8 fd 4b ef ff       	call   0xdf6be0
  f01fe3:	83 c4 14             	add    esp,0x14
  f01fe6:	6a 00                	push   0x0
  f01fe8:	6a 01                	push   0x1
  f01fea:	8b ce                	mov    ecx,esi
  f01fec:	e8 7f 4a ef ff       	call   0xdf6a70
  f01ff1:	6a 03                	push   0x3
  f01ff3:	6a 01                	push   0x1
  f01ff5:	8b ce                	mov    ecx,esi
  f01ff7:	e8 b4 4a ef ff       	call   0xdf6ab0
  f01ffc:	6a 03                	push   0x3
  f01ffe:	6a 00                	push   0x0
  f02000:	8b ce                	mov    ecx,esi
  f02002:	e8 89 4a ef ff       	call   0xdf6a90
  f02007:	5e                   	pop    esi
  f02008:	c3                   	ret
  f02009:	cc                   	int3
  f0200a:	cc                   	int3
  f0200b:	cc                   	int3
  f0200c:	cc                   	int3
  f0200d:	cc                   	int3
  f0200e:	cc                   	int3
  f0200f:	cc                   	int3
  f02010:	56                   	push   esi
  f02011:	8b 74 24 08          	mov    esi,DWORD PTR [esp+0x8]
  f02015:	6a 00                	push   0x0
  f02017:	6a 00                	push   0x0
  f02019:	6a fe                	push   0xfffffffe
  f0201b:	6a 14                	push   0x14
  f0201d:	6a 00                	push   0x0
  f0201f:	6a                 	push   0xb
