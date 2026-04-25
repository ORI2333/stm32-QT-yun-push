#include "stm32f10x.h"  



//初始化GPIO  参数分别为 GPIO时钟名称  GPIOX  GPIO_Pin   Periph_GPIO_Init(RCC_APB2Periph_GPIOB,GPIOB,GPIO_Pin_11);
void Periph_GPIO_Init(uint32_t RCC_APB2Periph,GPIO_TypeDef* GPIOx,uint16_t GPIO_Pin)//用于输出
{
	RCC_APB2PeriphClockCmd(RCC_APB2Periph,ENABLE);
	GPIO_InitTypeDef GPIO_InitStructure;
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;//推挽模式输出
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin;
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
	GPIO_Init(GPIOx,&GPIO_InitStructure);
	
}
//Periph_GPIO_Init_IPU(RCC_APB2Periph_GPIOB,GPIOB,GPIO_Pin_11);
void Periph_GPIO_Init_IPU(uint32_t RCC_APB2Periph,GPIO_TypeDef* GPIOx,uint16_t GPIO_Pin)//用于输入  若外置电路未加上下拉电阻，则不应当使用输入悬空模式
{
	RCC_APB2PeriphClockCmd(RCC_APB2Periph,ENABLE);
	GPIO_InitTypeDef GPIO_InitStructure;
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU;//上拉
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin;
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
	GPIO_Init(GPIOx,&GPIO_InitStructure);
	
}

void Periph_GPIO_Init_OD(uint32_t RCC_APB2Periph,GPIO_TypeDef* GPIOx,uint16_t GPIO_Pin)//开漏输出  不止可以输出若要进行输入，先输出1在读取输入数据寄存器
{
	RCC_APB2PeriphClockCmd(RCC_APB2Periph,ENABLE);
	GPIO_InitTypeDef GPIO_InitStructure;
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_OD;//开漏输出
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin;
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
	GPIO_Init(GPIOx,&GPIO_InitStructure);
	
}
